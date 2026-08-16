/* ROOTHEALTH_REPAIR_ROLE(TYPED_WAL_ADAPTER) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "attrib.h"
#include "endians.h"
#include "layout.h"
#include "roothealth_dirty.h"

struct rh_volume_record_info {
	uint16_t sequence;
	uint16_t attribute_instance;
	uint16_t flags;
	uint16_t usa_offset;
	uint16_t usa_count;
	uint32_t flag_offset;
};

static int rh_volume_record_parse(const ntfs_volume *volume,
		const unsigned char *record, struct rh_volume_record_info *info)
{
	const MFT_RECORD *mft = (const MFT_RECORD *)record;
	uint32_t bytes_in_use, bytes_allocated, offset;
	uint16_t usa_offset, usa_count;
	unsigned int found = 0;

	if (!volume || !record || !info || mft->magic != magic_FILE ||
			le32_to_cpu(mft->mft_record_number) != FILE_Volume ||
			le16_to_cpu(mft->flags) != le16_to_cpu(MFT_RECORD_IN_USE) ||
			le64_to_cpu(mft->base_mft_record)) {
		errno = EIO;
		return -1;
	}
	usa_offset = le16_to_cpu(mft->usa_ofs);
	usa_count = le16_to_cpu(mft->usa_count);
	bytes_in_use = le32_to_cpu(mft->bytes_in_use);
	bytes_allocated = le32_to_cpu(mft->bytes_allocated);
	offset = le16_to_cpu(mft->attrs_offset);
	if (bytes_allocated != volume->mft_record_size ||
			bytes_in_use < sizeof(*mft) || bytes_in_use > bytes_allocated ||
			(bytes_in_use & 7U) || offset < sizeof(*mft) || (offset & 7U) ||
			offset > bytes_in_use - 4U || usa_offset < sizeof(NTFS_RECORD) ||
			usa_count != volume->mft_record_size / volume->sector_size + 1U ||
			usa_offset > bytes_allocated ||
			(uint32_t)usa_count * 2U > bytes_allocated - usa_offset ||
			offset < (((uint32_t)usa_offset + (uint32_t)usa_count * 2U + 7U) &
				~UINT32_C(7))) {
		errno = EIO;
		return -1;
	}
	while (offset <= bytes_in_use - 4U) {
		const ATTR_RECORD *attribute = (const ATTR_RECORD *)(record + offset);
		uint32_t type = le32_to_cpu(attribute->type);
		uint32_t length, value_length, value_offset;

		if (type == 0xffffffffU)
			break;
		if (bytes_in_use - offset < 24U) {
			errno = EIO;
			return -1;
		}
		length = le32_to_cpu(attribute->length);
		if (attribute->non_resident || attribute->name_length || length < 24U ||
				(length & 7U) || length > bytes_in_use - offset) {
			errno = EIO;
			return -1;
		}
		value_length = le32_to_cpu(attribute->value_length);
		value_offset = le16_to_cpu(attribute->value_offset);
		if (value_offset < 24U || value_offset > length ||
				value_length > length - value_offset) {
			errno = EIO;
			return -1;
		}
		if (type == le32_to_cpu(AT_VOLUME_INFORMATION)) {
			const VOLUME_INFORMATION *information;
			uint16_t flags;

			if (found || value_length != sizeof(*information)) {
				errno = EIO;
				return -1;
			}
			information = (const VOLUME_INFORMATION *)
				(record + offset + value_offset);
			flags = le16_to_cpu(information->flags);
			if (flags & (uint16_t)~le16_to_cpu(VOLUME_FLAGS_MASK)) {
				errno = EIO;
				return -1;
			}
			info->flags = flags;
			info->attribute_instance = le16_to_cpu(attribute->instance);
			info->flag_offset = offset + value_offset +
				offsetof(VOLUME_INFORMATION, flags);
			found++;
		}
		offset += length;
	}
	if (offset > bytes_in_use - 4U ||
			le32_to_cpu(((const ATTR_RECORD *)(record + offset))->type) !=
				0xffffffffU || found != 1 ||
			info->flag_offset > volume->mft_record_size - sizeof(le16)) {
		errno = EIO;
		return -1;
	}
	info->sequence = le16_to_cpu(mft->sequence_number);
	info->usa_offset = usa_offset;
	info->usa_count = usa_count;
	return info->sequence ? 0 : -1;
}

static int rh_volume_records_canonically_equal(const unsigned char *primary,
		const struct rh_volume_record_info *primary_info,
		const unsigned char *mirror,
		const struct rh_volume_record_info *mirror_info, size_t length)
{
	size_t usa_begin, usa_end, i;

	if (!primary || !primary_info || !mirror || !mirror_info ||
			primary_info->usa_offset != mirror_info->usa_offset ||
			primary_info->usa_count != mirror_info->usa_count)
		return 0;
	usa_begin = primary_info->usa_offset;
	usa_end = usa_begin + (size_t)primary_info->usa_count * sizeof(uint16_t);
	if (usa_begin > length || usa_end > length)
		return 0;
	for (i = 0; i < length; i++) {
		if (i >= usa_begin && i < usa_end)
			continue;
		if (primary[i] != mirror[i])
			return 0;
	}
	return 1;
}

static int rh_record_base(const ntfs_volume *volume, int64_t lcn,
		uint64_t *base)
{
	uint64_t cluster;

	if (!volume || !base || lcn < 0 || lcn >= volume->nr_clusters) {
		errno = EIO;
		return -1;
	}
	cluster = (uint64_t)lcn << volume->cluster_size_bits;
	if (cluster > UINT64_MAX -
			((uint64_t)FILE_Volume << volume->mft_record_size_bits)) {
		errno = EOVERFLOW;
		return -1;
	}
	*base = cluster + ((uint64_t)FILE_Volume <<
		volume->mft_record_size_bits);
	return 0;
}

int rh_volume_dirty_inspect(ntfs_volume *volume, struct rh_writer *writer,
		int requested_dirty, struct rh_volume_dirty_pair *pair)
{
	unsigned char *primary = NULL, *mirror = NULL;
	struct rh_volume_record_info primary_info, mirror_info;
	le16 raw_flags;
	int result = -1;

	if (!volume || !writer || !pair || (requested_dirty != 0 &&
			requested_dirty != 1) || volume->sector_size != 512 ||
			volume->cluster_size != 4096 || volume->mft_record_size != 1024 ||
			volume->mftmirr_size <= FILE_Volume || !volume->mft_na ||
			!volume->mftmirr_na) {
		errno = EINVAL;
		return -1;
	}
	memset(pair, 0, sizeof(*pair));
	pair->requested_dirty = requested_dirty;
	primary = malloc(volume->mft_record_size);
	mirror = malloc(volume->mft_record_size);
	if (!primary || !mirror)
		goto out;
	if (ntfs_attr_mst_pread(volume->mft_na,
			(int64_t)FILE_Volume << volume->mft_record_size_bits, 1,
			volume->mft_record_size, primary) != 1 ||
			ntfs_attr_mst_pread(volume->mftmirr_na,
			(int64_t)FILE_Volume << volume->mft_record_size_bits, 1,
			volume->mft_record_size, mirror) != 1 ||
			rh_volume_record_parse(volume, primary, &primary_info) ||
			rh_volume_record_parse(volume, mirror, &mirror_info) ||
			primary_info.sequence != mirror_info.sequence ||
			primary_info.attribute_instance != mirror_info.attribute_instance ||
			primary_info.flags != mirror_info.flags ||
			primary_info.flag_offset != mirror_info.flag_offset ||
			!rh_volume_records_canonically_equal(primary, &primary_info,
				mirror, &mirror_info, volume->mft_record_size) ||
			rh_record_base(volume, volume->mft_lcn,
				&pair->primary_record_offset) ||
			rh_record_base(volume, volume->mftmirr_lcn,
				&pair->mirror_record_offset) ||
			pair->primary_record_offset > writer->device_size -
				volume->mft_record_size ||
			pair->mirror_record_offset > writer->device_size -
				volume->mft_record_size) {
		errno = EIO;
		goto out;
	}
	pair->primary_flag_offset = pair->primary_record_offset +
		primary_info.flag_offset;
	pair->mirror_flag_offset = pair->mirror_record_offset +
		mirror_info.flag_offset;
	if ((pair->primary_flag_offset & ~UINT64_C(511)) !=
			((pair->primary_flag_offset + sizeof(raw_flags) - 1U) &
			 ~UINT64_C(511)) ||
			(pair->mirror_flag_offset & ~UINT64_C(511)) !=
			((pair->mirror_flag_offset + sizeof(raw_flags) - 1U) &
			 ~UINT64_C(511)) ||
			rh_writer_read(writer, pair->primary_flag_offset,
				sizeof(raw_flags), &raw_flags) ||
			le16_to_cpu(raw_flags) != primary_info.flags ||
			rh_writer_read(writer, pair->mirror_flag_offset,
				sizeof(raw_flags), &raw_flags) ||
			le16_to_cpu(raw_flags) != mirror_info.flags) {
		errno = EIO;
		goto out;
	}
	pair->sequence = primary_info.sequence;
	pair->attribute_instance = primary_info.attribute_instance;
	pair->flags_before = primary_info.flags;
	pair->initially_dirty = !!(primary_info.flags &
		le16_to_cpu(VOLUME_IS_DIRTY));
	pair->flags_after = requested_dirty ?
		(uint16_t)(primary_info.flags | le16_to_cpu(VOLUME_IS_DIRTY)) :
		(uint16_t)(primary_info.flags &
			(uint16_t)~le16_to_cpu(VOLUME_IS_DIRTY));
	result = 0;
out:
	free(primary);
	free(mirror);
	return result;
}

int rh_volume_dirty_stage_pair(struct rh_writer *writer,
		struct rh_volume_dirty_pair *pair)
{
	le16 after;
	enum rh_write_kind kind;
	struct rh_write_semantic_target target;
	size_t checkpoint;

	if (!writer || !pair || !pair->sequence) {
		errno = EINVAL;
		return -1;
	}
	if (pair->flags_before == pair->flags_after)
		return 0;
	checkpoint = rh_writer_plan_checkpoint(writer);
	after = cpu_to_le16(pair->flags_after);
	kind = pair->requested_dirty ? RH_WRITE_VOLUME_DIRTY_SET :
		RH_WRITE_VOLUME_DIRTY_CLEAR;
	memset(&target, 0, sizeof(target));
	target.seal_version = 1;
	target.object = RH_WRITE_TARGET_MFT_RECORD_PRIMARY;
	target.owner_mft_record = FILE_Volume;
	target.owner_sequence = pair->sequence;
	target.attribute_instance = pair->attribute_instance;
	target.attribute_type = le32_to_cpu(AT_VOLUME_INFORMATION);
	target.flags = RH_WRITE_TARGET_PRIMARY | RH_WRITE_TARGET_RESIDENT |
		(pair->requested_dirty ? RH_WRITE_TARGET_SET_ONLY :
		 RH_WRITE_TARGET_CLEAR_ONLY);
	rh_sha256("", 0, target.attribute_name_hash);
	target.logical_offset = offsetof(VOLUME_INFORMATION, flags);
	target.logical_length = sizeof(after);
	target.semantic_target_offset = pair->primary_flag_offset;
	target.semantic_target_length = sizeof(after);
	target.lowest_vcn = -1;
	target.logical_vcn = -1;
	target.lcn = -1;
	if (rh_writer_plan_typed(writer, kind, pair->primary_flag_offset,
			sizeof(after), &after, &target))
		goto fail;
	target.object = RH_WRITE_TARGET_MFT_RECORD_MIRROR;
	target.flags &= (uint16_t)~RH_WRITE_TARGET_PRIMARY;
	target.flags |= RH_WRITE_TARGET_MIRROR;
	target.semantic_target_offset = pair->mirror_flag_offset;
	if (rh_writer_plan_typed(writer, kind, pair->mirror_flag_offset,
			sizeof(after), &after, &target) ||
			writer->operation_count != checkpoint + 2U)
		goto fail;
	pair->first_operation_ordinal = checkpoint + 1U;
	pair->planned = 1;
	return 0;
fail:
	(void)rh_writer_discard_after(writer, checkpoint);
	errno = EIO;
	return -1;
}
