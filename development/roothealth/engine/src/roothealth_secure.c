/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "attrib.h"
#include "device.h"
#include "dir.h"
#include "endians.h"
#include "inode.h"
#include "layout.h"
#include "mst.h"
#include "roothealth_secure.h"
#include "roothealth_secure_index.h"
#include "roothealth_secure_overlay.h"
#include "roothealth_secure_raw.h"
#include "roothealth_secure_reader.h"
#include "runlist.h"

#define RH_SECURE_VOLUME_MAX (UINT64_C(256) * 1024U * 1024U * 1024U)
#define RH_SDS_BLOCK UINT64_C(0x40000)
#define RH_SDS_PAIR UINT64_C(0x80000)
#define RH_SDS_ALIGN UINT64_C(16)
#define RH_SDS_HEADER ((size_t)offsetof(SDS_ENTRY, sid))
#define RH_SYSTEM_ACCESS_FILTER_ACE_TYPE 0x15U
#define RH_TRUST_PROTECTED_FILTER_ACE_FLAG 0x40U

struct rh_secure_copy_scan {
	struct rh_secure_descriptor *descriptors;
	struct rh_secure_descriptor *descriptors_by_offset;
	size_t descriptor_count;
	size_t descriptor_capacity;
	size_t offset_descriptor_count;
};

static int rh_secure_ranges_overlap(uint64_t first_offset,
		uint64_t first_length, uint64_t second_offset, uint64_t second_length);

static int rh_secure_all_zero(const unsigned char *bytes, size_t length)
{
	size_t i;

	for (i = 0; i < length; i++)
		if (bytes[i])
			return 0;
	return 1;
}

static int rh_secure_bool(int value)
{
	return value == 0 || value == 1;
}

static int rh_secure_identity_list_valid(const struct rh_secure_census *census)
{
	size_t i;

	if (!census || !census->live_security_ids ||
			!census->live_security_id_count ||
			census->live_security_id_count > SIZE_MAX / sizeof(uint32_t) ||
			census->security_ids_expected != census->live_security_id_count)
		return 0;
	for (i = 0; i < census->live_security_id_count; i++)
		if (census->live_security_ids[i] < 0x100U ||
				(i && census->live_security_ids[i] <=
				 census->live_security_ids[i - 1U]))
			return 0;
	return 1;
}

static void rh_secure_put_u32(unsigned char *out, uint32_t value)
{
	out[0] = (unsigned char)value;
	out[1] = (unsigned char)(value >> 8);
	out[2] = (unsigned char)(value >> 16);
	out[3] = (unsigned char)(value >> 24);
}

static void rh_secure_put_u64(unsigned char *out, uint64_t value)
{
	unsigned int i;

	for (i = 0; i < 8U; i++)
		out[i] = (unsigned char)(value >> (i * 8U));
}

static int rh_secure_census_valid(const struct rh_secure_census *census)
{
	int has_raw;

	if (!census)
		return 0;
	has_raw = census->raw_mft_census != NULL ||
		census->raw_mft_extent_authority_complete ||
		!rh_secure_all_zero(census->raw_mft_census_hash, 32);
	if (has_raw && (!census->raw_mft_census ||
			!census->raw_mft_extent_authority_complete ||
			!census->raw_mft_census->records_bounded ||
			!census->raw_mft_census->attribute_lists_complete ||
			!census->raw_mft_census->extents_complete ||
			census->raw_mft_census->generation != census->generation ||
			rh_secure_all_zero(census->raw_mft_census_hash, 32) ||
			memcmp(census->raw_mft_census_hash,
				census->raw_mft_census->census_hash, 32) ||
			census->legacy_security_descriptors_examined !=
				census->legacy_security_descriptors_expected ||
			(census->legacy_security_descriptors_expected &&
			 rh_secure_all_zero(census->legacy_security_descriptor_hash, 32))))
		return 0;
	return census->ledger_format == RH_SECURE_LEDGER_FORMAT &&
		(census->view == RH_SECURE_PRETRANSACTION ||
		 census->view == RH_SECURE_STAGED) && census->generation &&
		census->volume_serial && rh_secure_bool(census->coverage_complete) &&
		census->coverage_complete && rh_secure_bool(census->identity_bound) &&
		census->identity_bound &&
		rh_secure_bool(census->no_io_uncertainty) &&
		census->no_io_uncertainty &&
		rh_secure_bool(census->complete_mft_census) &&
		census->complete_mft_census &&
		rh_secure_bool(census->complete_attribute_census) &&
		census->complete_attribute_census &&
		rh_secure_bool(census->complete_runlist_census) &&
		census->complete_runlist_census &&
		rh_secure_bool(census->complete_namespace_census) &&
		census->complete_namespace_census &&
		rh_secure_bool(census->complete_index_census) &&
		census->complete_index_census &&
		rh_secure_bool(census->complete_security_descriptor_census) &&
		census->complete_security_descriptor_census &&
		rh_secure_bool(census->complete_security_id_census) &&
		census->complete_security_id_census &&
		rh_secure_bool(census->namespace_security_reciprocity_complete) &&
		census->namespace_security_reciprocity_complete &&
		rh_secure_bool(census->global_security_identity_complete) &&
		census->global_security_identity_complete &&
		rh_secure_bool(census->sole_valid_peer_authority_complete) &&
		census->sole_valid_peer_authority_complete &&
		rh_secure_bool(census->no_conflicting_valid_authorities) &&
		census->no_conflicting_valid_authorities &&
		rh_secure_bool(census->target_ownership_exact) &&
		census->target_ownership_exact &&
		rh_secure_bool(census->targets_outside_wal) &&
		census->targets_outside_wal && rh_secure_bool(census->data_preserving) &&
		census->data_preserving &&
		rh_secure_bool(census->final_overlay_valid) &&
		(census->view != RH_SECURE_STAGED || census->final_overlay_valid) &&
		census->mft_records_expected &&
		census->mft_records_examined == census->mft_records_expected &&
		census->attributes_expected &&
		census->attributes_examined == census->attributes_expected &&
		census->runs_expected && census->runs_examined == census->runs_expected &&
		census->namespace_links_expected &&
		census->namespace_links_examined == census->namespace_links_expected &&
		census->namespace_links_reciprocal == census->namespace_links_expected &&
		census->security_descriptors_expected &&
		census->security_descriptors_examined ==
			census->security_descriptors_expected &&
		census->security_ids_expected &&
		census->security_ids_examined == census->security_ids_expected &&
		rh_secure_identity_list_valid(census) &&
		census->security_id_references_examined ==
			census->security_id_references_expected &&
		census->security_id_references_resolved ==
			census->security_id_references_expected &&
		!rh_secure_all_zero(census->coverage_ledger_hash, 32) &&
		!rh_secure_all_zero(census->identity_graph_hash, 32) &&
		!rh_secure_all_zero(census->namespace_security_hash, 32) &&
		!rh_secure_all_zero(census->security_id_use_hash, 32) &&
		!rh_secure_all_zero(census->global_security_hash, 32) &&
		!rh_secure_all_zero(census->descriptor_manifest_hash, 32);
}

static int rh_secure_authority_hash(const struct rh_secure_census *census,
		unsigned char output[32])
{
	unsigned char *encoded;
	const uint64_t values[] = {
		census->ledger_format, (uint64_t)census->view, census->generation,
		census->volume_serial, (uint64_t)census->coverage_complete,
		(uint64_t)census->identity_bound,
		(uint64_t)census->no_io_uncertainty,
		(uint64_t)census->complete_mft_census,
		(uint64_t)census->complete_attribute_census,
		(uint64_t)census->complete_runlist_census,
		(uint64_t)census->complete_namespace_census,
		(uint64_t)census->complete_index_census,
		(uint64_t)census->complete_security_descriptor_census,
		(uint64_t)census->complete_security_id_census,
		(uint64_t)census->namespace_security_reciprocity_complete,
		(uint64_t)census->global_security_identity_complete,
		(uint64_t)census->sole_valid_peer_authority_complete,
		(uint64_t)census->no_conflicting_valid_authorities,
		(uint64_t)census->target_ownership_exact,
		(uint64_t)census->targets_outside_wal,
		(uint64_t)census->data_preserving,
		(uint64_t)census->final_overlay_valid,
		(uint64_t)census->raw_mft_extent_authority_complete,
		census->mft_records_expected, census->mft_records_examined,
		census->attributes_expected, census->attributes_examined,
		census->runs_expected, census->runs_examined,
		census->namespace_links_expected, census->namespace_links_examined,
		census->namespace_links_reciprocal,
		census->security_descriptors_expected,
		census->security_descriptors_examined,
		census->security_ids_expected, census->security_ids_examined,
		census->security_id_references_expected,
		census->security_id_references_examined,
		census->security_id_references_resolved,
		census->legacy_security_descriptors_expected,
		census->legacy_security_descriptors_examined,
		census->live_security_id_count,
	};
	const unsigned char *hashes[] = {
		census->coverage_ledger_hash, census->identity_graph_hash,
		census->namespace_security_hash, census->security_id_use_hash,
		census->global_security_hash, census->descriptor_manifest_hash,
		census->raw_mft_census_hash,
		census->legacy_security_descriptor_hash,
	};
	size_t total, cursor = 16U, i;

	if (!census || census->live_security_id_count >
			(SIZE_MAX - 1024U) / sizeof(uint32_t))
		return -1;
	total = 1024U + census->live_security_id_count * sizeof(uint32_t);
	encoded = calloc(1, total);
	if (!encoded)
		return -1;
	memcpy(encoded, "RHSECAUTH1", 10);
	rh_secure_put_u32(encoded + 10, RH_SECURE_AUTHORITY_VERSION);
	for (i = 0; i < sizeof(values) / sizeof(values[0]); i++) {
		if (cursor > total - 8U)
			goto error;
		rh_secure_put_u64(encoded + cursor, values[i]);
		cursor += 8U;
	}
	for (i = 0; i < sizeof(hashes) / sizeof(hashes[0]); i++) {
		if (cursor > total - 32U)
			goto error;
		memcpy(encoded + cursor, hashes[i], 32);
		cursor += 32U;
	}
	for (i = 0; i < census->live_security_id_count; i++) {
		if (cursor > total - 4U)
			goto error;
		rh_secure_put_u32(encoded + cursor, census->live_security_ids[i]);
		cursor += 4U;
	}
	rh_sha256(encoded, cursor, output);
	free(encoded);
	return 0;
error:
	free(encoded);
	return -1;
}

int rh_secure_authority_seal(const struct rh_secure_census *census,
		struct rh_secure_authority *authority)
{
	if (!authority || !rh_secure_census_valid(census)) {
		errno = EPERM;
		return -1;
	}
	memset(authority, 0, sizeof(*authority));
	authority->version = RH_SECURE_AUTHORITY_VERSION;
	authority->census = *census;
	authority->owned_live_security_ids = malloc(
		census->live_security_id_count * sizeof(uint32_t));
	if (!authority->owned_live_security_ids) {
		memset(authority, 0, sizeof(*authority));
		return -1;
	}
	memcpy(authority->owned_live_security_ids, census->live_security_ids,
		census->live_security_id_count * sizeof(uint32_t));
	authority->census.live_security_ids = authority->owned_live_security_ids;
	if (rh_secure_authority_hash(&authority->census, authority->seal)) {
		free(authority->owned_live_security_ids);
		memset(authority, 0, sizeof(*authority));
		if (!errno)
			errno = EINVAL;
		return -1;
	}
	return 0;
}

void rh_secure_authority_destroy(struct rh_secure_authority *authority)
{
	if (!authority)
		return;
	free(authority->owned_live_security_ids);
	memset(authority, 0, sizeof(*authority));
}

int rh_secure_authority_valid(const struct rh_secure_authority *authority,
		enum rh_secure_view view, uint64_t volume_serial,
		const unsigned char descriptor_manifest_hash[32])
{
	unsigned char seal[32];

	return authority && authority->version == RH_SECURE_AUTHORITY_VERSION &&
		authority->owned_live_security_ids &&
		authority->census.live_security_ids ==
			authority->owned_live_security_ids &&
		rh_secure_census_valid(&authority->census) &&
		authority->census.view == view &&
		authority->census.volume_serial == volume_serial &&
		descriptor_manifest_hash &&
		!memcmp(authority->census.descriptor_manifest_hash,
			descriptor_manifest_hash, 32) &&
		!rh_secure_authority_hash(&authority->census, seal) &&
		!memcmp(seal, authority->seal, 32);
}

static int rh_secure_read_serial(const struct rh_secure_read_source *source,
		uint64_t *serial)
{
	unsigned char bytes[8];
	unsigned int i;

	if (!serial || rh_secure_source_read(source, 72U, sizeof(bytes), bytes))
		return -1;
	*serial = 0;
	for (i = 0; i < 8U; i++)
		*serial |= (uint64_t)bytes[i] << (8U * i);
	return *serial ? 0 : -1;
}

static int rh_secure_sid_span(const unsigned char *bytes, size_t length,
		uint32_t offset, size_t *span)
{
	const SID *sid;
	size_t sid_length;

	if (!span)
		return 0;
	if ((offset & 3U) || offset > length || length - offset < 8U)
		return 0;
	sid = (const SID *)(bytes + offset);
	if (sid->revision != SID_REVISION ||
			sid->sub_authority_count > SID_MAX_SUB_AUTHORITIES)
		return 0;
	sid_length = 8U + (size_t)sid->sub_authority_count * 4U;
	if (sid_length > length - offset)
		return 0;
	*span = sid_length;
	return 1;
}

static int rh_secure_ranges_overlap(uint64_t first_offset,
		uint64_t first_length, uint64_t second_offset, uint64_t second_length);

static int rh_secure_ace_sid(const unsigned char *bytes, size_t length,
		size_t offset, int allow_application_data)
{
	size_t sid_length;

	if (offset > UINT32_MAX ||
			!rh_secure_sid_span(bytes, length, (uint32_t)offset, &sid_length))
		return 0;
	return allow_application_data ? offset + sid_length <= length :
		offset + sid_length == length;
}

static uint16_t rh_secure_get_u16(const unsigned char *bytes)
{
	return (uint16_t)bytes[0] | (uint16_t)((uint16_t)bytes[1] << 8);
}

static uint32_t rh_secure_get_u32(const unsigned char *bytes)
{
	return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) |
		((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
}

static uint64_t rh_secure_get_u64(const unsigned char *bytes)
{
	return (uint64_t)rh_secure_get_u32(bytes) |
		((uint64_t)rh_secure_get_u32(bytes + 4) << 32);
}

static int rh_secure_utf16_span(const unsigned char *bytes, size_t length,
		size_t offset, int require_nonempty, size_t *span)
{
	size_t cursor;

	if (!span || (offset & 1U) || offset > length || length - offset < 2U)
		return 0;
	for (cursor = offset; cursor <= length - 2U; cursor += 2U)
		if (!bytes[cursor] && !bytes[cursor + 1U]) {
			if (require_nonempty && cursor == offset)
				return 0;
			*span = cursor + 2U - offset;
			return 1;
		}
	return 0;
}

static int rh_secure_claim_value_span(const unsigned char *bytes,
		size_t length, uint16_t value_type, size_t table_end, size_t offset,
		size_t *span)
{
	uint32_t octet_length;
	size_t sid_length;

	if (!span || offset < table_end || offset > length)
		return 0;
	switch (value_type) {
	case 0x0001U:
	case 0x0002U:
		if ((offset & 3U) || length - offset < 8U)
			return 0;
		*span = 8U;
		return 1;
	case 0x0006U:
		if ((offset & 3U) || length - offset < 8U ||
				rh_secure_get_u64(bytes + offset) > 1U)
			return 0;
		*span = 8U;
		return 1;
	case 0x0003U:
		return rh_secure_utf16_span(bytes, length, offset, 0, span);
	case 0x0005U:
	case 0x0010U:
		if ((offset & 3U) || length - offset < 4U)
			return 0;
		octet_length = rh_secure_get_u32(bytes + offset);
		if (octet_length > length - offset - 4U)
			return 0;
		if (value_type == 0x0005U &&
				(!rh_secure_sid_span(bytes, length, (uint32_t)(offset + 4U),
					&sid_length) || sid_length != octet_length))
			return 0;
		*span = 4U + octet_length;
		return 1;
	default:
		return 0;
	}
}

static int rh_secure_claim_valid(const unsigned char *bytes, size_t length)
{
	uint32_t name_offset, flags, value_count;
	uint16_t value_type;
	size_t table_end, name_span, i, j;

	if (!bytes || length < 16U)
		return 0;
	name_offset = rh_secure_get_u32(bytes);
	value_type = rh_secure_get_u16(bytes + 4U);
	flags = rh_secure_get_u32(bytes + 8U);
	value_count = rh_secure_get_u32(bytes + 12U);
	/* Reserved is producer-zero but explicitly ignored by receivers. */
	if (value_count > (length - 16U) / 4U ||
			(flags & UINT32_C(0x0000ffc0)) ||
			((flags & 0x0002U) && value_type != 0x0003U))
		return 0;
	table_end = 16U + (size_t)value_count * 4U;
	if (name_offset < table_end ||
			!rh_secure_utf16_span(bytes, length, name_offset, 1, &name_span) ||
			name_span < 4U)
		return 0;
	for (i = 0; i < value_count; i++) {
		size_t value_offset = rh_secure_get_u32(bytes + 16U + i * 4U);
		size_t value_span;

		if (!rh_secure_claim_value_span(bytes, length, value_type, table_end,
				value_offset, &value_span) ||
				rh_secure_ranges_overlap(name_offset, name_span, value_offset,
					value_span))
			return 0;
		for (j = 0; j < i; j++) {
			size_t prior_offset = rh_secure_get_u32(bytes + 16U + j * 4U);
			size_t prior_span;

			if (!rh_secure_claim_value_span(bytes, length, value_type,
					table_end, prior_offset, &prior_span) ||
					(rh_secure_ranges_overlap(prior_offset, prior_span,
						value_offset, value_span) &&
					 (prior_offset != value_offset || prior_span != value_span)))
				return 0;
		}
	}
	return value_type == 0x0001U || value_type == 0x0002U ||
		value_type == 0x0003U || value_type == 0x0005U ||
		value_type == 0x0006U || value_type == 0x0010U;
}

static int rh_secure_everyone_sid(const unsigned char *bytes, size_t length,
		size_t *span)
{
	static const unsigned char everyone[12] = {
		1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0
	};

	return length >= sizeof(everyone) &&
		!memcmp(bytes, everyone, sizeof(everyone)) &&
		(*span = sizeof(everyone), 1);
}

static int rh_secure_mandatory_sid(const unsigned char *bytes, size_t length)
{
	const SID *sid = (const SID *)bytes;
	uint32_t rid;

	if (length < 12U || sid->revision != SID_REVISION ||
			sid->sub_authority_count != 1U ||
			sid->identifier_authority.value[0] ||
			sid->identifier_authority.value[1] ||
			sid->identifier_authority.value[2] ||
			sid->identifier_authority.value[3] ||
			sid->identifier_authority.value[4] ||
			sid->identifier_authority.value[5] != 16U)
		return 0;
	rid = le32_to_cpu(sid->sub_authority[0]);
	return rid == 0U || rid == 0x1000U || rid == 0x2000U ||
		rid == 0x3000U || rid == 0x4000U || rid == 0x5000U;
}

static int rh_secure_process_trust_sid(const unsigned char *bytes, size_t length)
{
	const SID *sid = (const SID *)bytes;
	uint32_t protection_type, protection_level;

	if (length != 16U || sid->revision != SID_REVISION ||
			sid->sub_authority_count != 2U ||
			sid->identifier_authority.value[0] ||
			sid->identifier_authority.value[1] ||
			sid->identifier_authority.value[2] ||
			sid->identifier_authority.value[3] ||
			sid->identifier_authority.value[4] ||
			sid->identifier_authority.value[5] != 19U)
		return 0;
	protection_type = le32_to_cpu(sid->sub_authority[0]);
	protection_level = le32_to_cpu(sid->sub_authority[1]);
	if (protection_type != 0U && protection_type != 0x200U &&
			protection_type != 0x400U)
		return 0;
	return protection_level == 0U || protection_level == 0x400U ||
		protection_level == 0x600U || protection_level == 0x800U ||
		protection_level == 0x1000U || protection_level == 0x2000U;
}

static int rh_secure_scoped_policy_sid(const unsigned char *bytes,
		size_t length)
{
	const SID *sid = (const SID *)bytes;

	return length >= 12U && sid->revision == SID_REVISION &&
		sid->sub_authority_count >= 1U &&
		!sid->identifier_authority.value[0] &&
		!sid->identifier_authority.value[1] &&
		!sid->identifier_authority.value[2] &&
		!sid->identifier_authority.value[3] &&
		!sid->identifier_authority.value[4] &&
		sid->identifier_authority.value[5] == 17U;
}

static int rh_secure_ace_valid(const unsigned char *bytes, size_t length,
		unsigned int acl_revision, int system_acl)
{
	const ACE_HEADER *header;
	unsigned int type, flags;
	size_t sid_offset;
	uint32_t object_flags;
	int callback;

	if (!bytes || length < sizeof(*header) || (length & 3U))
		return 0;
	header = (const ACE_HEADER *)bytes;
	type = (unsigned int)header->type;
	flags = (unsigned int)header->flags;
	if (le16_to_cpu(header->size) != length || (flags & 0x20U) ||
			((flags & 0xc0U) && type != SYSTEM_AUDIT_ACE_TYPE &&
			 type != SYSTEM_ALARM_ACE_TYPE &&
			 type != SYSTEM_AUDIT_OBJECT_ACE_TYPE &&
			 type != SYSTEM_ALARM_OBJECT_ACE_TYPE &&
			 type != SYSTEM_AUDIT_CALLBACK_ACE_TYPE &&
			 type != SYSTEM_ALARM_CALLBACK_ACE_TYPE &&
			 type != SYSTEM_AUDIT_CALLBACK_OBJECT_ACE_TYPE &&
			 type != SYSTEM_ALARM_CALLBACK_OBJECT_ACE_TYPE &&
			 type != RH_SYSTEM_ACCESS_FILTER_ACE_TYPE) ||
			(type == RH_SYSTEM_ACCESS_FILTER_ACE_TYPE && (flags & 0x80U)))
		return 0;
	callback = type == ACCESS_ALLOWED_CALLBACK_ACE_TYPE ||
		type == ACCESS_DENIED_CALLBACK_ACE_TYPE ||
		type == SYSTEM_AUDIT_CALLBACK_ACE_TYPE ||
		type == SYSTEM_ALARM_CALLBACK_ACE_TYPE;
	if (type == ACCESS_ALLOWED_ACE_TYPE || type == ACCESS_DENIED_ACE_TYPE ||
			type == SYSTEM_AUDIT_ACE_TYPE || type == SYSTEM_ALARM_ACE_TYPE ||
			callback) {
		if (length < 16U)
			return 0;
		return rh_secure_ace_sid(bytes, length, 8U, 1);
	}
	if (type == SYSTEM_MANDATORY_LABEL_ACE_TYPE ||
			type == SYSTEM_SCOPED_POLICY_ID_ACE_TYPE ||
			type == SYSTEM_PROCESS_TRUST_LABEL_ACE_TYPE) {
		size_t sid_length;

		if (!system_acl || length < 16U ||
				!rh_secure_sid_span(bytes, length, 8U, &sid_length) ||
				8U + sid_length > length)
			return 0;
		if (type == SYSTEM_MANDATORY_LABEL_ACE_TYPE &&
				((rh_secure_get_u32(bytes + 4U) & ~UINT32_C(7)) ||
				 !rh_secure_mandatory_sid(bytes + 8U, sid_length)))
			return 0;
		if (type == SYSTEM_SCOPED_POLICY_ID_ACE_TYPE &&
				(rh_secure_get_u32(bytes + 4U) ||
				 !rh_secure_scoped_policy_sid(bytes + 8U, sid_length)))
			return 0;
		if (type == SYSTEM_PROCESS_TRUST_LABEL_ACE_TYPE &&
				!rh_secure_process_trust_sid(bytes + 8U, sid_length))
			return 0;
		return 1;
	}
	if (type == ACCESS_ALLOWED_COMPOUND_ACE_TYPE) {
		/* mask + compound-type/reserved precede the SID. */
		if (acl_revision < ACL_REVISION3 || length < 20U ||
				rh_secure_get_u16(bytes + 8U) != 1U || bytes[10] || bytes[11])
			return 0;
		return rh_secure_ace_sid(bytes, length, 12U, 1);
	}
	callback = type == ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE ||
		type == ACCESS_DENIED_CALLBACK_OBJECT_ACE_TYPE ||
		type == SYSTEM_AUDIT_CALLBACK_OBJECT_ACE_TYPE ||
		type == SYSTEM_ALARM_CALLBACK_OBJECT_ACE_TYPE;
	if ((type >= ACCESS_ALLOWED_OBJECT_ACE_TYPE &&
			type <= SYSTEM_ALARM_OBJECT_ACE_TYPE) || callback) {
		if (acl_revision != ACL_REVISION_DS || length < 20U)
			return 0;
		object_flags = (uint32_t)bytes[8] |
			((uint32_t)bytes[9] << 8) |
			((uint32_t)bytes[10] << 16) |
			((uint32_t)bytes[11] << 24);
		if (object_flags & ~UINT32_C(3))
			return 0;
		sid_offset = 12U;
		if (object_flags & 1U)
			sid_offset += 16U;
		if (object_flags & 2U)
			sid_offset += 16U;
		return rh_secure_ace_sid(bytes, length, sid_offset, 1);
	}
	if (type == SYSTEM_RESOURCE_ATTRIBUTE_ACE_TYPE) {
		size_t sid_length;

		if (!system_acl || acl_revision != ACL_REVISION_DS || length < 36U ||
				rh_secure_get_u32(bytes + 4U) ||
				!rh_secure_everyone_sid(bytes + 8U, length - 8U, &sid_length))
			return 0;
		return rh_secure_claim_valid(bytes + 8U + sid_length,
			length - 8U - sid_length);
	}
	if (type == RH_SYSTEM_ACCESS_FILTER_ACE_TYPE) {
		size_t sid_length;

		if (!system_acl || acl_revision != ACL_REVISION_DS || length < 16U ||
				!rh_secure_sid_span(bytes, length, 8U, &sid_length) ||
				8U + sid_length > length)
			return 0;
		/* The SDK defines the post-SID filter condition as variable data.
		 * Receivers preserve it.  TP additionally requires a TrustLevelSid. */
		return !(flags & RH_TRUST_PROTECTED_FILTER_ACE_FLAG) ||
			rh_secure_process_trust_sid(bytes + 8U, sid_length);
	}
	return 0;
}

static int rh_secure_acl_span(const unsigned char *bytes, size_t length,
		uint32_t offset, int system_acl, size_t *span)
{
	const ACL *acl;
	size_t acl_size, cursor;
	uint16_t ace_count, i;

	if (!span)
		return 0;
	if ((offset & 3U) || offset > length || length - offset < sizeof(*acl))
		return 0;
	acl = (const ACL *)(bytes + offset);
	acl_size = le16_to_cpu(acl->size);
	ace_count = le16_to_cpu(acl->ace_count);
	if ((acl->revision < ACL_REVISION2 ||
			acl->revision > ACL_REVISION_DS) ||
			acl->alignment1 || le16_to_cpu(acl->alignment2) ||
			acl_size < sizeof(*acl) || (acl_size & 3U) ||
			acl_size > length - offset)
		return 0;
	cursor = sizeof(*acl);
	for (i = 0; i < ace_count; i++) {
		const ACE_HEADER *ace;
		size_t ace_size;

		if (cursor > acl_size || acl_size - cursor < sizeof(*ace))
			return 0;
		ace = (const ACE_HEADER *)((const unsigned char *)acl + cursor);
		ace_size = le16_to_cpu(ace->size);
		if (ace_size < sizeof(*ace) || (ace_size & 3U) ||
				ace_size > acl_size - cursor ||
				!rh_secure_ace_valid((const unsigned char *)acl + cursor,
					ace_size, acl->revision, system_acl))
			return 0;
		cursor += ace_size;
	}
	if (cursor > acl_size)
		return 0;
	*span = acl_size;
	return 1;
}

static uint32_t rh_secure_descriptor_hash(const unsigned char *bytes,
		size_t length)
{
	uint32_t hash = 0;
	size_t i;

	for (i = 0; i < length; i += 4U) {
		uint32_t word = (uint32_t)bytes[i] |
			((uint32_t)bytes[i + 1U] << 8) |
			((uint32_t)bytes[i + 2U] << 16) |
			((uint32_t)bytes[i + 3U] << 24);
		hash = (hash << 3) | (hash >> 29);
		hash += word;
	}
	return hash;
}

static int rh_secure_descriptor_valid(const unsigned char *bytes,
		size_t length)
{
	const SECURITY_DESCRIPTOR_RELATIVE *descriptor;
	uint16_t control;
	uint32_t owner, group, sacl, dacl;
	uint32_t offsets[4];
	size_t spans[4];
	int kinds[4];
	size_t count = 0, i, j;

	if (!bytes || length < sizeof(*descriptor) || (length & 3U))
		return 0;
	descriptor = (const SECURITY_DESCRIPTOR_RELATIVE *)bytes;
	control = le16_to_cpu(descriptor->control);
	owner = le32_to_cpu(descriptor->owner);
	group = le32_to_cpu(descriptor->group);
	sacl = le32_to_cpu(descriptor->sacl);
	dacl = le32_to_cpu(descriptor->dacl);
	if (descriptor->revision != SECURITY_DESCRIPTOR_REVISION ||
			(descriptor->alignment && !(control & 0x4000U)) ||
			!(control & 0x8000U) ||
			(control & (uint16_t)~0xff3fU) ||
			(sacl && !(control & 0x0010U)) ||
			(dacl && !(control & 0x0004U)) ||
			(!(control & 0x0010U) && (sacl || (control & 0x0020U))) ||
			(!(control & 0x0004U) && (dacl || (control & 0x0008U))))
		return 0;
	if (owner) {
		offsets[count] = owner;
		kinds[count] = 0;
		if (owner < sizeof(*descriptor) ||
				!rh_secure_sid_span(bytes, length, owner, &spans[count++]))
			return 0;
	}
	if (group) {
		offsets[count] = group;
		kinds[count] = 0;
		if (group < sizeof(*descriptor) ||
				!rh_secure_sid_span(bytes, length, group, &spans[count++]))
			return 0;
	}
	if (sacl) {
		offsets[count] = sacl;
		kinds[count] = 1;
		if (sacl < sizeof(*descriptor) ||
				!rh_secure_acl_span(bytes, length, sacl, 1, &spans[count++]))
			return 0;
	}
	if (dacl) {
		offsets[count] = dacl;
		kinds[count] = 1;
		if (dacl < sizeof(*descriptor) ||
				!rh_secure_acl_span(bytes, length, dacl, 0, &spans[count++]))
			return 0;
	}
	for (i = 0; i < count; i++)
		for (j = i + 1U; j < count; j++)
			if (rh_secure_ranges_overlap(offsets[i], spans[i], offsets[j],
					spans[j]) && !(kinds[i] == 0 && kinds[j] == 0 &&
					offsets[i] == offsets[j] && spans[i] == spans[j]))
				return 0;
	return 1;
}

int rh_secure_descriptor_bytes_valid(const void *bytes, size_t length)
{
	return rh_secure_descriptor_valid(bytes, length);
}

static int rh_secure_legacy_attribute_compare(const void *left,
		const void *right)
{
	const struct rh_raw_attribute *const *first = left;
	const struct rh_raw_attribute *const *second = right;

	if ((*first)->owner.record != (*second)->owner.record)
		return (*first)->owner.record < (*second)->owner.record ? -1 : 1;
	return (*first)->instance < (*second)->instance ? -1 :
		(*first)->instance > (*second)->instance ? 1 : 0;
}

static int rh_secure_legacy_census_internal(
		const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *census,
		uint64_t *descriptor_count, unsigned char manifest_hash[32])
{
	const struct rh_raw_attribute **legacy = NULL;
	unsigned char *manifest = NULL;
	unsigned char *allocated_descriptor = NULL;
	unsigned char digest[32];
	size_t count = 0, i, j, total;
	int result = -1;

	if (!census || !descriptor_count || !manifest_hash) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; i < census->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &census->attributes[i];
		void *grown;

		if (attribute->type != AT_SECURITY_DESCRIPTOR)
			continue;
		/* A nonresident stream contributes one descriptor, not one
		 * descriptor per extent.  The assembled-stream reader below proves
		 * every continuation extent through the raw ATTRIBUTE_LIST census. */
		if (attribute->nonresident && attribute->lowest_vcn)
			continue;
		if (count >= SIZE_MAX / sizeof(*legacy)) {
			errno = EOVERFLOW;
			goto out;
		}
		grown = realloc(legacy, (count + 1U) * sizeof(*legacy));
		if (!grown)
			goto out;
		legacy = grown;
		legacy[count++] = attribute;
	}
	if (!count) {
		*descriptor_count = 0;
		memset(manifest_hash, 0, 32);
		result = 0;
		goto out;
	}
	qsort(legacy, count, sizeof(*legacy),
		rh_secure_legacy_attribute_compare);
	if (count > (SIZE_MAX - 16U) / 80U) {
		errno = EOVERFLOW;
		goto out;
	}
	total = 16U + count * 80U;
	manifest = calloc(1, total);
	if (!manifest)
		goto out;
	memcpy(manifest, "RHSECLEG", 8);
	rh_secure_put_u64(manifest + 8U, count);
	for (i = 0; i < count; i++) {
		const struct rh_raw_attribute *attribute = legacy[i];
		const struct rh_raw_mft_slot *owner_slot;
		const unsigned char *descriptor;
		size_t descriptor_length;
		const struct rh_raw_attribute *standard = NULL;
		unsigned char value_hash[32];
		size_t base = 16U + i * 80U;

		if ((i && legacy[i - 1U]->owner.record == attribute->owner.record) ||
				attribute->flags || attribute->name_length ||
				!attribute->owner.sequence ||
				attribute->owner.record >= census->slot_count ||
				census->slots[attribute->owner.record].state !=
					RH_RAW_SLOT_LIVE_BASE ||
				census->slots[attribute->owner.record].sequence !=
					attribute->owner.sequence) {
			errno = EUCLEAN;
			goto out;
		}
		if (!attribute->nonresident && (attribute->resident_flags ||
				attribute->value_arena_offset > census->value_arena_size ||
				attribute->value_length > census->value_arena_size -
					attribute->value_arena_offset)) {
			errno = EUCLEAN;
			goto out;
		}
		if (attribute->nonresident && (!reader || attribute->lowest_vcn ||
				attribute->data_size <= 0 ||
				attribute->initialized_size != attribute->data_size ||
				(uint64_t)attribute->data_size > SIZE_MAX)) {
			errno = EUCLEAN;
			goto out;
		}
		owner_slot = &census->slots[attribute->owner.record];
		if (owner_slot->attribute_first > census->attribute_count ||
				owner_slot->attribute_count > census->attribute_count -
					owner_slot->attribute_first) {
			errno = EUCLEAN;
			goto out;
		}
		if (attribute->nonresident) {
			descriptor_length = (size_t)attribute->data_size;
			allocated_descriptor = malloc(descriptor_length);
			if (!allocated_descriptor)
				goto out;
			if (rh_raw_mft_stream_pread_reader(reader, census,
					attribute->owner, AT_SECURITY_DESCRIPTOR, NULL, 0,
					0, descriptor_length, allocated_descriptor))
				goto out;
			descriptor = allocated_descriptor;
		} else {
			descriptor = census->value_arena + attribute->value_arena_offset;
			descriptor_length = attribute->value_length;
		}
		if (!rh_secure_descriptor_valid(descriptor, descriptor_length)) {
			errno = EUCLEAN;
			goto out;
		}
		rh_sha256(descriptor, descriptor_length, value_hash);
		if (!attribute->nonresident &&
				memcmp(value_hash, attribute->value_hash, 32)) {
			errno = EUCLEAN;
			goto out;
		}
		for (j = 0; j < owner_slot->attribute_count; j++) {
			const struct rh_raw_attribute *candidate = &census->attributes[
				owner_slot->attribute_first + j];

			if (candidate->owner.record != attribute->owner.record ||
					candidate->owner.sequence != attribute->owner.sequence ||
					candidate->type != AT_STANDARD_INFORMATION)
				continue;
			if (standard) {
				errno = EUCLEAN;
				goto out;
			}
			standard = candidate;
		}
		/* Legacy standard information is exactly 48 bytes and has no
		 * central $Secure security-id field. */
		if (!standard || standard->nonresident || standard->flags ||
				standard->resident_flags || standard->name_length ||
				standard->value_length != 48U) {
			errno = EUCLEAN;
			goto out;
		}
		rh_secure_put_u64(manifest + base, attribute->owner.record);
		rh_secure_put_u64(manifest + base + 8U, attribute->owner.sequence);
		rh_secure_put_u64(manifest + base + 16U, attribute->storage.record);
		rh_secure_put_u64(manifest + base + 24U,
			attribute->storage.sequence);
		rh_secure_put_u64(manifest + base + 32U, attribute->instance);
		rh_secure_put_u64(manifest + base + 40U, descriptor_length);
		memcpy(manifest + base + 48U, value_hash, 32);
		free(allocated_descriptor);
		allocated_descriptor = NULL;
	}
	rh_sha256(manifest, total, digest);
	*descriptor_count = count;
	memcpy(manifest_hash, digest, 32);
	result = 0;
out:
	free(manifest);
	free(legacy);
	free(allocated_descriptor);
	return result;
}

int rh_secure_legacy_census(const struct rh_raw_mft_census *census,
		uint64_t *descriptor_count, unsigned char manifest_hash[32])
{
	return rh_secure_legacy_census_internal(NULL, census, descriptor_count,
		manifest_hash);
}

int rh_secure_legacy_census_reader(const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *census,
		uint64_t *descriptor_count, unsigned char manifest_hash[32])
{
	return rh_secure_legacy_census_internal(reader, census, descriptor_count,
		manifest_hash);
}

static int rh_secure_validate_legacy_descriptors(
		const struct rh_secure_read_source *source,
		const struct rh_secure_census *authority)
{
	struct rh_census_reader writer_reader;
	const struct rh_census_reader *reader = source->reader;
	unsigned char manifest_hash[32];
	uint64_t descriptor_count;

	if (!reader && source->writer) {
		if (rh_census_reader_from_writer_prefix(source->writer,
				source->writer->operation_count, &writer_reader))
			return -1;
		reader = &writer_reader;
	}
	if ((reader ? rh_secure_legacy_census_reader(reader,
			authority->raw_mft_census, &descriptor_count, manifest_hash) :
			rh_secure_legacy_census(authority->raw_mft_census,
			&descriptor_count, manifest_hash)))
		return -1;
	if (descriptor_count != authority->legacy_security_descriptors_expected ||
			descriptor_count !=
				authority->legacy_security_descriptors_examined ||
			memcmp(manifest_hash,
				authority->legacy_security_descriptor_hash, 32)) {
		errno = EUCLEAN;
		return -1;
	}
	return 0;
}

static void rh_secure_copy_scan_destroy(struct rh_secure_copy_scan *scan)
{
	if (!scan)
		return;
	free(scan->descriptors_by_offset);
	free(scan->descriptors);
	memset(scan, 0, sizeof(*scan));
}

static size_t rh_secure_identity_index(const uint32_t *security_ids,
		size_t security_id_count, uint32_t security_id)
{
	size_t low = 0, high = security_id_count;

	while (low < high) {
		size_t middle = low + (high - low) / 2U;

		if (security_ids[middle] == security_id)
			return middle;
		if (security_ids[middle] < security_id)
			low = middle + 1U;
		else
			high = middle;
	}
	return SIZE_MAX;
}

static int rh_secure_descriptor_id_compare(const void *left, const void *right)
{
	const struct rh_secure_descriptor *first = left;
	const struct rh_secure_descriptor *second = right;

	return first->security_id < second->security_id ? -1 :
		first->security_id > second->security_id ? 1 : 0;
}

static int rh_secure_descriptor_offset_compare(const void *left,
		const void *right)
{
	const struct rh_secure_descriptor *first = left;
	const struct rh_secure_descriptor *second = right;

	return first->offset < second->offset ? -1 :
		first->offset > second->offset ? 1 : 0;
}

static int rh_secure_scan_grow(struct rh_secure_copy_scan *scan)
{
	size_t capacity;
	void *grown;

	if (scan->descriptor_count < scan->descriptor_capacity)
		return 0;
	capacity = scan->descriptor_capacity ? scan->descriptor_capacity : 32U;
	if (capacity > SIZE_MAX / 2U ||
			capacity * 2U > SIZE_MAX / sizeof(*scan->descriptors)) {
		errno = EOVERFLOW;
		return -1;
	}
	capacity *= 2U;
	grown = realloc(scan->descriptors,
		capacity * sizeof(*scan->descriptors));
	if (!grown)
		return -1;
	scan->descriptors = grown;
	scan->descriptor_capacity = capacity;
	return 0;
}

static int rh_secure_scan_copy(const unsigned char *bytes, size_t length,
		uint64_t primary_base, const uint32_t *security_ids,
		size_t security_id_count, struct rh_secure_copy_scan *scan)
{
	size_t cursor;

	memset(scan, 0, sizeof(*scan));
	for (cursor = 0; cursor <= length && length - cursor >= RH_SDS_HEADER;
			cursor += RH_SDS_ALIGN) {
		const SDS_ENTRY *entry = (const SDS_ENTRY *)(bytes + cursor);
		uint32_t entry_length = le32_to_cpu(entry->length);
		uint32_t security_id = le32_to_cpu(entry->security_id);
		uint64_t recorded_offset = le64_to_cpu(entry->offset);
		struct rh_secure_descriptor *grown;
		int self_pointing = recorded_offset == primary_base + cursor;
		int referenced = rh_secure_identity_index(security_ids,
			security_id_count, security_id) != SIZE_MAX;

		/*
		 * Examine every aligned slot, including slots inside a corrupt claimed
		 * entry.  That is required to prove parse uniqueness instead of silently
		 * selecting whichever resynchronization path happens to run first.
		 * Gaps and retired IDs remain opaque and are never made authoritative.
		 */
		if (!self_pointing || !referenced)
			continue;
		if (scan->descriptor_count >= security_id_count) {
			errno = EUCLEAN;
			goto error;
		}
		if (rh_secure_scan_grow(scan))
			goto error;
		grown = &scan->descriptors[scan->descriptor_count++];
		memset(grown, 0, sizeof(*grown));
		grown->security_id = security_id;
		grown->offset = primary_base + cursor;
		if (entry_length >= RH_SDS_HEADER +
				sizeof(SECURITY_DESCRIPTOR_RELATIVE) &&
				entry_length <= length - cursor &&
				!((entry_length - RH_SDS_HEADER) & 3U) &&
				rh_secure_descriptor_valid(bytes + cursor + RH_SDS_HEADER,
					entry_length - RH_SDS_HEADER) &&
				rh_secure_descriptor_hash(bytes + cursor + RH_SDS_HEADER,
					entry_length - RH_SDS_HEADER) ==
					le32_to_cpu(entry->hash)) {
			grown->hash = le32_to_cpu(entry->hash);
			grown->length = entry_length;
			rh_sha256(bytes + cursor + RH_SDS_HEADER,
				entry_length - RH_SDS_HEADER, grown->descriptor_hash);
		}
	}
	qsort(scan->descriptors, scan->descriptor_count,
		sizeof(*scan->descriptors), rh_secure_descriptor_offset_compare);
	/* A referenced candidate nested in any other bounded self-pointing entry
	 * admits two parses and therefore cannot establish sole authority. */
	for (cursor = 0; cursor <= length && length - cursor >= RH_SDS_HEADER;
			cursor += RH_SDS_ALIGN) {
		const SDS_ENTRY *outer = (const SDS_ENTRY *)(bytes + cursor);
		uint32_t outer_length = le32_to_cpu(outer->length);
		uint64_t outer_offset = le64_to_cpu(outer->offset);
		size_t low = 0, high = scan->descriptor_count;
		uint64_t start = primary_base + cursor;

		if (outer_offset != primary_base + cursor ||
				outer_length < RH_SDS_HEADER +
					sizeof(SECURITY_DESCRIPTOR_RELATIVE) ||
				(outer_length & 3U) || outer_length > length - cursor)
			continue;
		while (low < high) {
			size_t middle = low + (high - low) / 2U;

			if (scan->descriptors[middle].offset <= start)
				low = middle + 1U;
			else
				high = middle;
		}
		if (low < scan->descriptor_count &&
				scan->descriptors[low].offset - start < outer_length) {
			errno = EUCLEAN;
			goto error;
		}
	}
	qsort(scan->descriptors, scan->descriptor_count,
		sizeof(*scan->descriptors), rh_secure_descriptor_id_compare);
	for (cursor = 1; cursor < scan->descriptor_count; cursor++)
		if (scan->descriptors[cursor - 1U].security_id ==
				scan->descriptors[cursor].security_id) {
			errno = EUCLEAN;
			goto error;
		}
	if (scan->descriptor_count > SIZE_MAX /
			sizeof(*scan->descriptors_by_offset)) {
		errno = EOVERFLOW;
		goto error;
	}
	scan->descriptors_by_offset = malloc(scan->descriptor_count *
		sizeof(*scan->descriptors_by_offset));
	if (scan->descriptor_count && !scan->descriptors_by_offset)
		goto error;
	for (cursor = 0; cursor < scan->descriptor_count; cursor++)
		if (scan->descriptors[cursor].length)
			scan->descriptors_by_offset[scan->offset_descriptor_count++] =
				scan->descriptors[cursor];
	qsort(scan->descriptors_by_offset, scan->offset_descriptor_count,
		sizeof(*scan->descriptors_by_offset),
		rh_secure_descriptor_offset_compare);
	/* Valid live entries form a unique, non-overlapping interval set. */
	for (cursor = 1; cursor < scan->offset_descriptor_count; cursor++) {
		const struct rh_secure_descriptor *previous =
			&scan->descriptors_by_offset[cursor - 1U];
		const struct rh_secure_descriptor *current =
			&scan->descriptors_by_offset[cursor];

		if (previous->length && current->length &&
				rh_secure_ranges_overlap(previous->offset, previous->length,
					current->offset, current->length)) {
			errno = EUCLEAN;
			goto error;
		}
	}
	return 0;
error:
	rh_secure_copy_scan_destroy(scan);
	return -1;
}

static int rh_secure_ranges_overlap(uint64_t first_offset,
		uint64_t first_length, uint64_t second_offset, uint64_t second_length)
{
	if (!first_length || !second_length)
		return 0;
	if (first_offset <= second_offset)
		return second_offset - first_offset < first_length;
	return first_offset - second_offset < second_length;
}

#ifdef ROOTHEALTH_TESTING
int rh_secure_test_ranges_overlap(uint64_t first_offset,
		uint64_t first_length, uint64_t second_offset, uint64_t second_length)
{
	return rh_secure_ranges_overlap(first_offset, first_length,
		second_offset, second_length);
}
#endif

static int rh_secure_restore_range_safe(const struct rh_secure_copy_scan *peer,
		uint32_t security_id, uint64_t offset, uint64_t length)
{
	size_t low = 0, high = peer->offset_descriptor_count;

	if (!length || length > UINT64_MAX - offset)
		return 0;
	while (low < high) {
		size_t middle = low + (high - low) / 2U;

		if (peer->descriptors_by_offset[middle].offset < offset)
			low = middle + 1U;
		else
			high = middle;
	}
	if (low && peer->descriptors_by_offset[low - 1U].length &&
			peer->descriptors_by_offset[low - 1U].security_id != security_id &&
			rh_secure_ranges_overlap(offset, length,
				peer->descriptors_by_offset[low - 1U].offset,
				peer->descriptors_by_offset[low - 1U].length))
		return 0;
	if (low < peer->offset_descriptor_count &&
			peer->descriptors_by_offset[low].length &&
			peer->descriptors_by_offset[low].security_id != security_id &&
			rh_secure_ranges_overlap(offset, length,
				peer->descriptors_by_offset[low].offset,
				peer->descriptors_by_offset[low].length))
		return 0;
	return 1;
}

static int rh_secure_reconcile_sds(struct rh_secure_inspection *inspection,
		const uint32_t *security_ids, size_t security_id_count)
{
	uint64_t base;
	size_t i;

	if (!inspection || inspection->descriptors || inspection->descriptor_count ||
			!security_id_count || security_id_count >
				SIZE_MAX / sizeof(*inspection->descriptors)) {
		errno = EOVERFLOW;
		return -1;
	}
	inspection->descriptors = malloc(security_id_count *
		sizeof(*inspection->descriptors));
	if (!inspection->descriptors)
		return -1;

	for (base = 0; base < inspection->sds_data_size; base += RH_SDS_PAIR) {
		struct rh_secure_copy_scan primary, backup;
		size_t primary_length, backup_length;
		unsigned char *primary_bytes, *backup_bytes;

		primary_length = (size_t)(inspection->sds_data_size - base);
		if (primary_length > RH_SDS_BLOCK)
			primary_length = RH_SDS_BLOCK;
		if (inspection->sds_data_size <= base + RH_SDS_BLOCK) {
			errno = ENOTSUP;
			return -1;
		}
		backup_length = (size_t)(inspection->sds_data_size -
			(base + RH_SDS_BLOCK));
		if (backup_length > RH_SDS_BLOCK)
			backup_length = RH_SDS_BLOCK;
		primary_bytes = inspection->sds_current + base;
		backup_bytes = inspection->sds_current + base + RH_SDS_BLOCK;
		if (rh_secure_scan_copy(primary_bytes, primary_length, base,
				security_ids, security_id_count, &primary))
			return -1;
		if (rh_secure_scan_copy(backup_bytes, backup_length, base,
				security_ids, security_id_count, &backup)) {
			rh_secure_copy_scan_destroy(&primary);
			return -1;
		}
		{
			size_t pi = 0, bi = 0;

		while (pi < primary.descriptor_count || bi < backup.descriptor_count) {
			const struct rh_secure_descriptor *p = NULL, *b = NULL;
			const struct rh_secure_descriptor *authority = NULL;
			uint64_t relative;
			uint32_t security_id;

			if (bi >= backup.descriptor_count ||
					(pi < primary.descriptor_count &&
					 primary.descriptors[pi].security_id <=
					 backup.descriptors[bi].security_id))
				security_id = primary.descriptors[pi].security_id;
			else
				security_id = backup.descriptors[bi].security_id;
			if (pi < primary.descriptor_count &&
					primary.descriptors[pi].security_id == security_id)
				p = &primary.descriptors[pi++];
			if (bi < backup.descriptor_count &&
					backup.descriptors[bi].security_id == security_id)
				b = &backup.descriptors[bi++];

			if (p && b && p->offset != b->offset)
				goto refused_pair;
			if (p && p->length && b && b->length) {
				relative = p->offset - base;
				if (p->length != b->length ||
						memcmp(p, b, sizeof(*p)) ||
						relative > primary_length ||
						p->length > primary_length - relative ||
						relative > backup_length ||
						p->length > backup_length - relative ||
						memcmp(primary_bytes + relative,
							backup_bytes + relative, p->length))
					goto refused_pair;
				authority = p;
			} else if (p && p->length) {
				relative = p->offset - base;
				if (relative > backup_length ||
						p->length > backup_length - relative ||
						!rh_secure_restore_range_safe(&backup,
							p->security_id, p->offset, p->length))
					goto refused_pair;
				memcpy(inspection->sds_staged + base + RH_SDS_BLOCK +
					relative, primary_bytes + relative, p->length);
				authority = p;
			} else if (b && b->length) {
				relative = b->offset - base;
				if (relative > primary_length ||
						b->length > primary_length - relative ||
						!rh_secure_restore_range_safe(&primary,
							b->security_id, b->offset, b->length))
					goto refused_pair;
				memcpy(inspection->sds_staged + base + relative,
					backup_bytes + relative, b->length);
				authority = b;
			} else
				goto refused_pair;
			if (inspection->descriptor_count >= security_id_count)
				goto refused_pair;
			inspection->descriptors[inspection->descriptor_count++] = *authority;
		}
		}
		rh_secure_copy_scan_destroy(&backup);
		rh_secure_copy_scan_destroy(&primary);
		continue;
refused_pair:
		rh_secure_copy_scan_destroy(&backup);
		rh_secure_copy_scan_destroy(&primary);
		errno = EUCLEAN;
		return -1;
	}
	if (inspection->descriptor_count != security_id_count) {
		errno = EUCLEAN;
		return -1;
	}
	qsort(inspection->descriptors, inspection->descriptor_count,
		sizeof(*inspection->descriptors), rh_secure_descriptor_id_compare);
	for (i = 0; i < security_id_count; i++)
		if (inspection->descriptors[i].security_id != security_ids[i]) {
			errno = EUCLEAN;
			return -1;
		}
	return 0;
}

static int rh_secure_build_manifest(struct rh_secure_inspection *inspection)
{
	unsigned char *encoded;
	size_t total, cursor = 16U, i;

	if (!inspection || !inspection->descriptor_count ||
			inspection->descriptor_count >
			(SIZE_MAX - 16U) / 64U)
		return -1;
	total = 16U + inspection->descriptor_count * 64U;
	encoded = calloc(1, total);
	if (!encoded)
		return -1;
	memcpy(encoded, "RHSECMAN1", 9);
	rh_secure_put_u64(encoded + 8, inspection->descriptor_count);
	for (i = 0; i < inspection->descriptor_count; i++) {
		const struct rh_secure_descriptor *descriptor =
			&inspection->descriptors[i];
		rh_secure_put_u32(encoded + cursor, descriptor->hash);
		rh_secure_put_u32(encoded + cursor + 4U,
			descriptor->security_id);
		rh_secure_put_u64(encoded + cursor + 8U, descriptor->offset);
		rh_secure_put_u32(encoded + cursor + 16U, descriptor->length);
		memcpy(encoded + cursor + 24U, descriptor->descriptor_hash, 32);
		cursor += 64U;
	}
	rh_sha256(encoded, total, inspection->descriptor_manifest_hash);
	free(encoded);
	return 0;
}

static int rh_secure_build_sds_mapping(ntfs_volume *volume,
		struct rh_writer *writer, ntfs_attr *attribute,
		struct rh_secure_inspection *inspection)
{
	runlist_element *run;
	uint64_t expected_vcn = 0, covered = 0, allocated_clusters;

	if (!volume || !writer || !attribute || !inspection ||
			!NAttrNonResident(attribute) || attribute->name_len != 4U ||
			attribute->type != AT_DATA || attribute->data_flags ||
			attribute->data_size <= (int64_t)RH_SDS_BLOCK ||
			(uint64_t)attribute->data_size > SIZE_MAX ||
			attribute->initialized_size != attribute->data_size ||
			attribute->allocated_size < attribute->data_size ||
			(attribute->allocated_size % volume->cluster_size) ||
			ntfs_attr_map_whole_runlist(attribute))
		return -1;
	allocated_clusters = (uint64_t)attribute->allocated_size /
		volume->cluster_size;
	for (run = attribute->rl; run && run->length; run++) {
		uint64_t run_bytes, take, physical;
		struct rh_secure_mapping_slice *grown;

		if (run->vcn < 0 || run->lcn < 0 || run->length <= 0 ||
				(uint64_t)run->vcn != expected_vcn ||
				expected_vcn > allocated_clusters ||
				(uint64_t)run->length > allocated_clusters - expected_vcn ||
				(uint64_t)run->length > UINT64_MAX / volume->cluster_size ||
				(uint64_t)run->lcn > UINT64_MAX / volume->cluster_size)
			return -1;
		run_bytes = (uint64_t)run->length * volume->cluster_size;
		physical = (uint64_t)run->lcn * volume->cluster_size;
		if (physical > writer->device_size ||
				run_bytes > writer->device_size - physical)
			return -1;
		take = run_bytes;
		if (covered > (uint64_t)attribute->data_size)
			return -1;
		if (take > (uint64_t)attribute->data_size - covered)
			take = (uint64_t)attribute->data_size - covered;
		if (take) {
			if (inspection->sds_slice_count >=
					SIZE_MAX / sizeof(*inspection->sds_slices)) {
				errno = EOVERFLOW;
				return -1;
			}
			if (rh_writer_range_excluded(writer, physical, (size_t)take))
				return -1;
			grown = realloc(inspection->sds_slices,
				(inspection->sds_slice_count + 1U) * sizeof(*grown));
			if (!grown)
				return -1;
			inspection->sds_slices = grown;
			grown = &inspection->sds_slices[inspection->sds_slice_count++];
			grown->logical_offset = covered;
			grown->length = take;
			grown->physical_offset = physical;
			grown->logical_vcn = run->vcn;
			grown->lcn = run->lcn;
			grown->storage_mft_record = FILE_Secure;
			grown->storage_sequence = inspection->owner_sequence;
			grown->attribute_instance = inspection->sds_instance;
			grown->lowest_vcn = 0;
			covered += take;
		}
		expected_vcn += (uint64_t)run->length;
	}
	if (!run || run->length || run->vcn < 0 || run->lcn != LCN_ENOENT ||
			(uint64_t)run->vcn != expected_vcn ||
			expected_vcn != allocated_clusters ||
			covered != (uint64_t)attribute->data_size ||
			!inspection->sds_slice_count)
		return -1;
	inspection->sds_data_size = (uint64_t)attribute->data_size;
	return 0;
}

static int rh_secure_read_mapping(const struct rh_secure_read_source *source,
		const struct rh_secure_mapping_slice *slices, size_t slice_count,
		unsigned char *bytes, uint64_t length)
{
	size_t i;

	if (!rh_secure_source_valid(source) || !slices || !slice_count ||
			!bytes || !length)
		return -1;
	for (i = 0; i < slice_count; i++) {
		const struct rh_secure_mapping_slice *slice = &slices[i];

		if (slice->logical_offset > length ||
				slice->length > length - slice->logical_offset ||
				slice->length > SIZE_MAX ||
				rh_secure_source_read(source, slice->physical_offset,
					(size_t)slice->length, bytes + slice->logical_offset))
			return -1;
	}
	return 0;
}

static int rh_secure_mft_record_physical(ntfs_volume *volume,
		const struct rh_secure_read_source *source, uint64_t record,
		uint64_t *physical)
{
	runlist_element *run;
	uint64_t logical, vcn, within;

	if (!volume || !volume->mft_na || !rh_secure_source_valid(source) ||
			!physical ||
			volume->mft_record_size != 1024U ||
			ntfs_attr_map_whole_runlist(volume->mft_na))
		return -1;
	logical = record * volume->mft_record_size;
	vcn = logical / volume->cluster_size;
	within = logical % volume->cluster_size;
	for (run = volume->mft_na->rl; run && run->length; run++)
		if (run->vcn >= 0 && run->lcn >= 0 && run->length > 0 &&
				vcn >= (uint64_t)run->vcn &&
				vcn - (uint64_t)run->vcn < (uint64_t)run->length) {
			uint64_t lcn = (uint64_t)run->lcn + vcn - (uint64_t)run->vcn;
			uint64_t offset = lcn * volume->cluster_size + within;
			int excluded;

			if ((offset & 1023U) || offset > rh_secure_source_size(source) ||
					1024U > rh_secure_source_size(source) - offset)
				return -1;
			excluded = rh_secure_source_excluded(source, offset, 1024U);
			if (excluded)
				return -1;
			*physical = offset;
			return 0;
		}
	return -1;
}

static int rh_secure_sdh_compare(const void *left, const void *right)
{
	const struct rh_secure_descriptor *const *a = left;
	const struct rh_secure_descriptor *const *b = right;

	if ((*a)->hash != (*b)->hash)
		return (*a)->hash < (*b)->hash ? -1 : 1;
	if ((*a)->security_id != (*b)->security_id)
		return (*a)->security_id < (*b)->security_id ? -1 : 1;
	return 0;
}

static int rh_secure_build_index_root(
		const struct rh_secure_inspection *inspection, int sdh,
		unsigned char **bytes, size_t *length)
{
	struct rh_secure_descriptor **ordered = NULL;
	INDEX_ROOT *root;
	unsigned char *result, *cursor;
	size_t entry_size = sdh ? 0x30U : 0x28U;
	size_t required, i;

	if (!inspection || !inspection->descriptor_count || !bytes || !length ||
			inspection->descriptor_count >
			(SIZE_MAX - sizeof(INDEX_ROOT) - sizeof(INDEX_ENTRY_HEADER)) /
				entry_size)
		return -1;
	required = sizeof(INDEX_ROOT) + inspection->descriptor_count * entry_size +
		sizeof(INDEX_ENTRY_HEADER);
	result = calloc(1, required);
	ordered = calloc(inspection->descriptor_count, sizeof(*ordered));
	if (!result || !ordered)
		goto error;
	for (i = 0; i < inspection->descriptor_count; i++)
		ordered[i] = &inspection->descriptors[i];
	if (sdh)
		qsort(ordered, inspection->descriptor_count, sizeof(*ordered),
			rh_secure_sdh_compare);
	root = (INDEX_ROOT *)result;
	root->type = AT_UNUSED;
	root->collation_rule = sdh ? COLLATION_NTOFS_SECURITY_HASH :
		COLLATION_NTOFS_ULONG;
	root->index_block_size = cpu_to_le32(4096U);
	root->clusters_per_index_block = 1;
	root->index.entries_offset = cpu_to_le32(sizeof(INDEX_HEADER));
	root->index.index_length = cpu_to_le32(required - offsetof(INDEX_ROOT, index));
	root->index.allocated_size = root->index.index_length;
	root->index.ih_flags = SMALL_INDEX;
	cursor = result + sizeof(INDEX_ROOT);
	for (i = 0; i < inspection->descriptor_count; i++) {
		INDEX_ENTRY *entry = (INDEX_ENTRY *)cursor;
		const struct rh_secure_descriptor *descriptor = ordered[i];
		SECURITY_DESCRIPTOR_HEADER *data;

		entry->data_offset = cpu_to_le16(sdh ? 0x18U : 0x14U);
		entry->data_length = cpu_to_le16(0x14U);
		entry->length = cpu_to_le16((uint16_t)entry_size);
		entry->key_length = cpu_to_le16(sdh ? 8U : 4U);
		if (sdh) {
			SDH_INDEX_DATA *sdh_data;

			entry->key.sdh.hash = cpu_to_le32(descriptor->hash);
			entry->key.sdh.security_id =
				cpu_to_le32(descriptor->security_id);
			sdh_data = (SDH_INDEX_DATA *)(cursor + 0x18U);
			sdh_data->hash = cpu_to_le32(descriptor->hash);
			sdh_data->security_id = cpu_to_le32(descriptor->security_id);
			sdh_data->offset = cpu_to_le64(descriptor->offset);
			sdh_data->length = cpu_to_le32(descriptor->length);
			sdh_data->reserved_II = cpu_to_le32(0x00490049U);
		} else {
			entry->key.sii.security_id =
				cpu_to_le32(descriptor->security_id);
			data = (SECURITY_DESCRIPTOR_HEADER *)(cursor + 0x14U);
			data->hash = cpu_to_le32(descriptor->hash);
			data->security_id = cpu_to_le32(descriptor->security_id);
			data->offset = cpu_to_le64(descriptor->offset);
			data->length = cpu_to_le32(descriptor->length);
		}
		cursor += entry_size;
	}
	((INDEX_ENTRY_HEADER *)cursor)->length =
		cpu_to_le16(sizeof(INDEX_ENTRY_HEADER));
	((INDEX_ENTRY_HEADER *)cursor)->flags = INDEX_ENTRY_END;
	free(ordered);
	*bytes = result;
	*length = required;
	return 0;
error:
	free(ordered);
	free(result);
	return -1;
}

static int rh_secure_mapping_hash(struct rh_secure_inspection *inspection)
{
	unsigned char *encoded;
	const struct rh_secure_index_state *indexes[2];
	size_t slice_total, total, cursor = 384U, i, which;

	if (!inspection || !inspection->sds_slice_count)
		return -1;
	indexes[0] = &inspection->sdh_index;
	indexes[1] = &inspection->sii_index;
	slice_total = inspection->sds_slice_count;
	for (which = 0; which < 2; which++) {
		if (indexes[which]->allocation_slice_count > SIZE_MAX - slice_total)
			return -1;
		slice_total += indexes[which]->allocation_slice_count;
		if (indexes[which]->bitmap_slice_count > SIZE_MAX - slice_total)
			return -1;
		slice_total += indexes[which]->bitmap_slice_count;
	}
	if (slice_total > (SIZE_MAX - 384U) / 64U)
		return -1;
	total = 384U + slice_total * 64U;
	encoded = calloc(1, total);
	if (!encoded)
		return -1;
	memcpy(encoded, "RHSECMAP3", 9);
	rh_secure_put_u64(encoded + 16, inspection->volume_serial);
	rh_secure_put_u64(encoded + 24, inspection->mft_record_physical);
	rh_secure_put_u64(encoded + 32, inspection->sds_data_size);
	rh_secure_put_u64(encoded + 40, inspection->sds_slice_count);
	rh_secure_put_u64(encoded + 48, inspection->sds_instance);
	for (which = 0; which < 2; which++) {
		const struct rh_secure_index_state *index = indexes[which];
		size_t base = 64U + which * 128U;

		rh_secure_put_u64(encoded + base, (uint64_t)index->large);
		rh_secure_put_u64(encoded + base + 8U,
			which ? inspection->sii_instance : inspection->sdh_instance);
		rh_secure_put_u64(encoded + base + 16U,
			which ? inspection->sii_semantic_physical :
			inspection->sdh_semantic_physical);
		rh_secure_put_u64(encoded + base + 24U,
			which ? inspection->sii_value_length :
			inspection->sdh_value_length);
		rh_secure_put_u64(encoded + base + 32U,
			index->allocation_instance);
		rh_secure_put_u64(encoded + base + 40U,
			index->allocation_data_size);
		rh_secure_put_u64(encoded + base + 48U,
			index->allocation_slice_count);
		rh_secure_put_u64(encoded + base + 56U, index->bitmap_instance);
		rh_secure_put_u64(encoded + base + 64U, index->bitmap_data_size);
		rh_secure_put_u64(encoded + base + 72U,
			index->bitmap_resident ? index->bitmap_semantic_physical :
			index->bitmap_slice_count);
		rh_secure_put_u64(encoded + base + 80U,
			index->root_storage_mft_record);
		rh_secure_put_u64(encoded + base + 88U,
			index->root_storage_sequence);
		rh_secure_put_u64(encoded + base + 96U,
			index->root_record_physical);
		rh_secure_put_u64(encoded + base + 104U,
			index->bitmap_storage_mft_record);
		rh_secure_put_u64(encoded + base + 112U,
			index->bitmap_storage_sequence);
		rh_secure_put_u64(encoded + base + 120U,
			index->bitmap_record_physical);
	}
	for (i = 0; i < inspection->sds_slice_count; i++) {
		const struct rh_secure_mapping_slice *slice = &inspection->sds_slices[i];
		rh_secure_put_u64(encoded + cursor, slice->logical_offset);
		rh_secure_put_u64(encoded + cursor + 8U, slice->length);
		rh_secure_put_u64(encoded + cursor + 16U, slice->physical_offset);
		rh_secure_put_u64(encoded + cursor + 24U,
			(uint64_t)slice->logical_vcn);
		rh_secure_put_u64(encoded + cursor + 32U, (uint64_t)slice->lcn);
		rh_secure_put_u64(encoded + cursor + 40U,
			slice->storage_mft_record);
		rh_secure_put_u64(encoded + cursor + 48U,
			((uint64_t)slice->storage_sequence << 16) |
			slice->attribute_instance);
		rh_secure_put_u64(encoded + cursor + 56U,
			(uint64_t)slice->lowest_vcn);
		cursor += 64U;
	}
	for (which = 0; which < 2; which++) {
		const struct rh_secure_index_state *index = indexes[which];
		const struct rh_secure_mapping_slice *sets[2] = {
			index->allocation_slices, index->bitmap_slices
		};
		const size_t counts[2] = {
			index->allocation_slice_count, index->bitmap_slice_count
		};
		size_t set;

		for (set = 0; set < 2; set++)
			for (i = 0; i < counts[set]; i++) {
				const struct rh_secure_mapping_slice *slice = &sets[set][i];

				rh_secure_put_u64(encoded + cursor,
					((uint64_t)which << 63) | ((uint64_t)set << 62) |
					(slice->logical_offset & (UINT64_MAX >> 2)));
				rh_secure_put_u64(encoded + cursor + 8U, slice->length);
				rh_secure_put_u64(encoded + cursor + 16U,
					slice->physical_offset);
				rh_secure_put_u64(encoded + cursor + 24U,
					(uint64_t)slice->logical_vcn);
				rh_secure_put_u64(encoded + cursor + 32U,
					(uint64_t)slice->lcn);
				rh_secure_put_u64(encoded + cursor + 40U,
					slice->storage_mft_record);
				rh_secure_put_u64(encoded + cursor + 48U,
					((uint64_t)slice->storage_sequence << 16) |
					slice->attribute_instance);
				rh_secure_put_u64(encoded + cursor + 56U,
					(uint64_t)slice->lowest_vcn);
				cursor += 64U;
			}
	}
	if (cursor != total) {
		free(encoded);
		return -1;
	}
	rh_sha256(encoded, total, inspection->mapping_hash);
	free(encoded);
	return 0;
}

static int rh_secure_inspect_common(ntfs_volume *volume,
		const struct rh_secure_read_source *source,
		const struct rh_secure_census *census,
		struct rh_secure_inspection *inspection)
{
	struct rh_writer *writer = source ? source->writer : NULL;
	ntfs_inode *inode = NULL;
	ntfs_attr *sds = NULL;
	ntfs_attr_search_ctx *sds_search = NULL;
	unsigned char *sdh = NULL, *sii = NULL;
	size_t sdh_length = 0, sii_length = 0;
	uint64_t serial;
	int result = -1;

	if (!volume || !rh_secure_source_valid(source) || !inspection || !census ||
			!census->complete_security_id_census ||
			census->security_ids_examined != census->security_ids_expected ||
			!rh_secure_identity_list_valid(census) ||
			volume->sector_size != 512U ||
			volume->cluster_size != 4096U || volume->mft_record_size != 1024U ||
			volume->indx_record_size != 4096U ||
			rh_secure_source_size(source) > RH_SECURE_VOLUME_MAX ||
			rh_secure_read_serial(source, &serial)) {
		errno = EINVAL;
		return -1;
	}
	errno = 0;
	memset(inspection, 0, sizeof(*inspection));
	inode = ntfs_inode_open(volume, FILE_Secure);
	if (!inode || !inode->mrec || inode->mft_no != FILE_Secure ||
			inode->mrec->magic != magic_FILE ||
			le32_to_cpu(inode->mrec->mft_record_number) != FILE_Secure ||
			!(inode->mrec->flags & MFT_RECORD_IN_USE) ||
			!le16_to_cpu(inode->mrec->sequence_number) ||
			le64_to_cpu(inode->mrec->base_mft_record) ||
			rh_secure_mft_record_physical(volume, source, FILE_Secure,
				&inspection->mft_record_physical))
		goto out;
	inspection->owner_mft_record = FILE_Secure;
	inspection->owner_sequence = le16_to_cpu(inode->mrec->sequence_number);
	if (census->raw_mft_census) {
		if (!rh_secure_raw_census_valid(census->raw_mft_census,
				census->generation, inspection->owner_sequence) ||
				memcmp(census->raw_mft_census_hash,
					census->raw_mft_census->census_hash, 32) ||
				rh_secure_validate_legacy_descriptors(source, census))
			goto out;
		inspection->raw_mft_census = census->raw_mft_census;
	} else if (NInoAttrList(inode) || inode->nr_extents) {
		errno = EPERM;
		goto out;
	}
	sds_search = ntfs_attr_get_search_ctx(inode, NULL);
	if (!sds_search || ntfs_attr_lookup(AT_DATA, STREAM_SDS, 4,
			CASE_SENSITIVE, 0, NULL, 0, sds_search) ||
			(!inspection->raw_mft_census && sds_search->ntfs_ino != inode) ||
			!sds_search->attr ||
			!sds_search->attr->non_resident)
		goto out;
	inspection->sds_instance = le16_to_cpu(sds_search->attr->instance);
	sds = ntfs_attr_open(inode, AT_DATA, STREAM_SDS, 4);
	if (!sds)
		goto out;
	if (inspection->raw_mft_census) {
		struct rh_raw_mft_ref owner = {
			FILE_Secure, inspection->owner_sequence
		};

		if ((writer ? rh_secure_raw_build_mapping(
				inspection->raw_mft_census, writer, owner, AT_DATA,
				(const unsigned char *)STREAM_SDS, 4, RH_SDS_BLOCK + 1U,
				SIZE_MAX, &inspection->sds_slices,
				&inspection->sds_slice_count, &inspection->sds_data_size) :
				rh_secure_raw_build_mapping_reader(
				inspection->raw_mft_census, source->reader, owner, AT_DATA,
				(const unsigned char *)STREAM_SDS, 4, RH_SDS_BLOCK + 1U,
				SIZE_MAX, &inspection->sds_slices,
				&inspection->sds_slice_count, &inspection->sds_data_size)))
			goto out;
		inspection->sds_instance =
			inspection->sds_slices[0].attribute_instance;
	} else if (!writer || rh_secure_build_sds_mapping(volume, writer, sds,
			inspection))
		goto out;
	inspection->sds_current = malloc(inspection->sds_data_size);
	inspection->sds_staged = malloc(inspection->sds_data_size);
	if (!inspection->sds_current || !inspection->sds_staged ||
			rh_secure_read_mapping(source, inspection->sds_slices,
				inspection->sds_slice_count, inspection->sds_current,
				inspection->sds_data_size))
		goto out;
	memcpy(inspection->sds_staged, inspection->sds_current,
		inspection->sds_data_size);
	if (rh_secure_reconcile_sds(inspection, census->live_security_ids,
			census->live_security_id_count) ||
			rh_secure_build_manifest(inspection) ||
			rh_secure_build_index_root(inspection, 1, &sdh, &sdh_length) ||
			rh_secure_build_index_root(inspection, 0, &sii, &sii_length))
		goto out;
	inspection->sdh_canonical = sdh;
	inspection->sii_canonical = sii;
	inspection->sdh_value_length = sdh_length;
	inspection->sii_value_length = sii_length;
	inspection->volume_serial = serial;
	sdh = sii = NULL;
	if ((writer ? rh_secure_index_inspect(volume, writer, inode, inspection, 1) :
			rh_secure_index_inspect_reader(volume, source->reader, inode,
				inspection, 1)) ||
			(writer ? rh_secure_index_inspect(volume, writer, inode, inspection,
				0) : rh_secure_index_inspect_reader(volume, source->reader, inode,
				inspection, 0)) ||
			rh_secure_mapping_hash(inspection))
		goto out;
	rh_sha256(inspection->sds_current, inspection->sds_data_size,
		inspection->sds_current_hash);
	rh_sha256(inspection->sds_staged, inspection->sds_data_size,
		inspection->sds_staged_hash);
	inspection->sds_clean = !memcmp(inspection->sds_current_hash,
		inspection->sds_staged_hash, 32);
	result = 0;
out:
	free(sdh);
	free(sii);
	if (sds)
		ntfs_attr_close(sds);
	if (sds_search)
		ntfs_attr_put_search_ctx(sds_search);
	if (inode)
		ntfs_inode_close(inode);
	if (result) {
		rh_secure_inspection_destroy(inspection);
		if (!errno)
			errno = ENOTSUP;
	}
	return result;
}

int rh_secure_inspect(ntfs_volume *volume, struct rh_writer *writer,
		const struct rh_secure_census *census,
		struct rh_secure_inspection *inspection)
{
	const struct rh_secure_read_source source = { writer, NULL };

	return rh_secure_inspect_common(volume, &source, census, inspection);
}

int rh_secure_inspect_reader(ntfs_volume *volume,
		const struct rh_census_reader *reader,
		const struct rh_secure_census *census,
		struct rh_secure_inspection *inspection)
{
	const struct rh_secure_read_source source = { NULL, reader };

	return rh_secure_inspect_common(volume, &source, census, inspection);
}

void rh_secure_inspection_destroy(struct rh_secure_inspection *inspection)
{
	if (!inspection)
		return;
	if (inspection->sds_current) {
		memset(inspection->sds_current, 0, inspection->sds_data_size);
		free(inspection->sds_current);
	}
	if (inspection->sds_staged) {
		memset(inspection->sds_staged, 0, inspection->sds_data_size);
		free(inspection->sds_staged);
	}
	free(inspection->sdh_canonical);
	free(inspection->sii_canonical);
	free(inspection->descriptors);
	free(inspection->sds_slices);
	rh_secure_index_state_destroy(&inspection->sdh_index);
	rh_secure_index_state_destroy(&inspection->sii_index);
	memset(inspection, 0, sizeof(*inspection));
}

static void rh_secure_name_hash(const char *name, unsigned char hash[32])
{
	unsigned char encoded[32];
	size_t length = strlen(name), i;

	memset(encoded, 0, sizeof(encoded));
	for (i = 0; i < length; i++)
		encoded[2U * i] = (unsigned char)name[i];
	rh_sha256(encoded, length * 2U, hash);
}

static void rh_secure_nonresident_target(
		const struct rh_secure_inspection *inspection,
		const struct rh_secure_mapping_slice *slice, uint64_t relative,
		uint64_t length, struct rh_write_semantic_target *target)
{
	uint64_t cluster_delta = relative / 4096U;

	memset(target, 0, sizeof(*target));
	target->seal_version = 1;
	target->object = RH_WRITE_TARGET_NONRESIDENT_ATTRIBUTE;
	target->owner_mft_record = FILE_Secure;
	target->owner_sequence = inspection->owner_sequence;
	target->attribute_instance = slice->attribute_instance;
	target->attribute_type = AT_DATA;
	target->attribute_name_length = 4;
	target->flags = RH_WRITE_TARGET_NONRESIDENT;
	rh_secure_name_hash("$SDS", target->attribute_name_hash);
	target->lowest_vcn = slice->lowest_vcn;
	target->logical_vcn = slice->logical_vcn + (int64_t)cluster_delta;
	target->logical_offset = slice->logical_offset + relative;
	target->logical_length = length;
	target->semantic_target_offset = slice->physical_offset + relative;
	target->semantic_target_length = length;
	target->lcn = slice->lcn + (int64_t)cluster_delta;
}

static int rh_secure_add_sds_write(
		const struct rh_secure_inspection *inspection,
		const struct rh_secure_mapping_slice *slice, uint64_t start,
		uint64_t length, struct rh_overlay_expected_write **writes,
		const unsigned char ***bytes, size_t *count)
{
	struct rh_overlay_expected_write *grown_writes;
	const unsigned char **grown_bytes;
	struct rh_write_semantic_target target;

	if (!length || length > SIZE_MAX ||
			*count >= SIZE_MAX / sizeof(**writes) ||
			*count >= SIZE_MAX / sizeof(**bytes)) {
		errno = EOVERFLOW;
		return -1;
	}
	rh_secure_nonresident_target(inspection, slice, start, length, &target);
	if (!rh_write_semantic_target_valid(RH_WRITE_SECURE_SDS, &target,
			target.semantic_target_offset, (size_t)length, 0))
		return -1;
	grown_writes = realloc(*writes, (*count + 1U) * sizeof(**writes));
	if (!grown_writes)
		return -1;
	*writes = grown_writes;
	grown_bytes = realloc((void *)*bytes,
		(*count + 1U) * sizeof(**bytes));
	if (!grown_bytes)
		return -1;
	*bytes = grown_bytes;
	(*writes)[*count].offset = target.semantic_target_offset;
	(*writes)[*count].length = length;
	(*writes)[*count].target = target;
	(*bytes)[*count] = inspection->sds_staged +
		slice->logical_offset + start;
	(*count)++;
	return 0;
}

static int rh_secure_build_sds_writes(
		const struct rh_secure_inspection *inspection,
		struct rh_overlay_expected_write **writes,
		const unsigned char ***bytes, size_t *count)
{
	size_t i;

	*writes = NULL;
	*bytes = NULL;
	*count = 0;
	for (i = 0; i < inspection->sds_slice_count; i++) {
		const struct rh_secure_mapping_slice *slice =
			&inspection->sds_slices[i];
		uint64_t cursor = 0;

		while (cursor < slice->length) {
			uint64_t start, end;

			while (cursor < slice->length &&
					inspection->sds_current[slice->logical_offset + cursor] ==
					inspection->sds_staged[slice->logical_offset + cursor])
				cursor++;
			if (cursor == slice->length)
				break;
			start = cursor;
			while (cursor < slice->length &&
					inspection->sds_current[slice->logical_offset + cursor] !=
					inspection->sds_staged[slice->logical_offset + cursor])
				cursor++;
			end = cursor;
			start &= ~(RH_SDS_ALIGN - 1U);
			end = (end + RH_SDS_ALIGN - 1U) & ~(RH_SDS_ALIGN - 1U);
			if (end > slice->length)
				end = slice->length;
			if (rh_secure_add_sds_write(inspection, slice, start,
					end - start, writes, bytes, count))
				goto error;
			cursor = end;
		}
	}
	return *count ? 0 : -1;
error:
	free(*writes);
	free((void *)*bytes);
	*writes = NULL;
	*bytes = NULL;
	*count = 0;
	return -1;
}

static void rh_secure_evidence_hash(
		const struct rh_secure_authority *authority,
		const struct rh_secure_inspection *inspection,
		unsigned char output[32])
{
	unsigned char encoded[352];

	memset(encoded, 0, sizeof(encoded));
	memcpy(encoded, "RHSECEVID1", 10);
	rh_secure_put_u64(encoded + 16, authority->census.generation);
	rh_secure_put_u64(encoded + 24, inspection->volume_serial);
	rh_secure_put_u64(encoded + 32, inspection->descriptor_count);
	rh_secure_put_u64(encoded + 40, inspection->sds_data_size);
	memcpy(encoded + 48, authority->seal, 32);
	memcpy(encoded + 80, inspection->descriptor_manifest_hash, 32);
	memcpy(encoded + 112, inspection->mapping_hash, 32);
	memcpy(encoded + 144, inspection->sds_current_hash, 32);
	memcpy(encoded + 176, inspection->sds_staged_hash, 32);
	memcpy(encoded + 208, inspection->sdh_current_hash, 32);
	memcpy(encoded + 240, inspection->sdh_canonical_hash, 32);
	memcpy(encoded + 272, inspection->sii_current_hash, 32);
	memcpy(encoded + 304, inspection->sii_canonical_hash, 32);
	rh_sha256(encoded, sizeof(encoded), output);
}

static void rh_secure_state_hash(const struct rh_secure_inspection *inspection,
		unsigned char output[32])
{
	unsigned char encoded[320];

	memset(encoded, 0, sizeof(encoded));
	memcpy(encoded, "RHSECSTATE1", 11);
	rh_secure_put_u64(encoded + 16U, inspection->volume_serial);
	rh_secure_put_u64(encoded + 24U, inspection->descriptor_count);
	rh_secure_put_u64(encoded + 32U, inspection->sds_data_size);
	memcpy(encoded + 48U, inspection->descriptor_manifest_hash, 32);
	memcpy(encoded + 80U, inspection->mapping_hash, 32);
	memcpy(encoded + 112U, inspection->sds_current_hash, 32);
	memcpy(encoded + 144U, inspection->sds_staged_hash, 32);
	memcpy(encoded + 176U, inspection->sdh_current_hash, 32);
	memcpy(encoded + 208U, inspection->sdh_canonical_hash, 32);
	memcpy(encoded + 240U, inspection->sii_current_hash, 32);
	memcpy(encoded + 272U, inspection->sii_canonical_hash, 32);
	rh_sha256(encoded, sizeof(encoded), output);
}

static void rh_secure_batch_cursor_hash(
		const struct rh_secure_batch_cursor *cursor, unsigned char output[32])
{
	unsigned char encoded[184];

	memset(encoded, 0, sizeof(encoded));
	memcpy(encoded, "RHSECBATCH1", 11);
	rh_secure_put_u32(encoded + 12U, cursor->version);
	rh_secure_put_u32(encoded + 16U, cursor->complete);
	rh_secure_put_u64(encoded + 24U, cursor->generation);
	rh_secure_put_u64(encoded + 32U, cursor->volume_serial);
	rh_secure_put_u64(encoded + 40U, cursor->next_batch_ordinal);
	rh_secure_put_u64(encoded + 48U, cursor->operations_completed);
	memcpy(encoded + 56U, cursor->descriptor_manifest_hash, 32);
	memcpy(encoded + 88U, cursor->mapping_hash, 32);
	memcpy(encoded + 120U, cursor->expected_state_hash, 32);
	rh_sha256(encoded, sizeof(encoded), output);
}

static int rh_secure_batch_cursor_empty(
		const struct rh_secure_batch_cursor *cursor)
{
	const unsigned char *bytes = (const unsigned char *)cursor;

	return cursor && rh_secure_all_zero(bytes, sizeof(*cursor));
}

static int rh_secure_batch_cursor_valid(
		const struct rh_secure_batch_cursor *cursor,
		const struct rh_secure_authority *authority,
		const struct rh_secure_inspection *inspection,
		const unsigned char state_hash[32])
{
	unsigned char seal[32];

	if (!cursor || cursor->version != RH_SECURE_BATCH_CURSOR_VERSION ||
			cursor->complete || cursor->generation != authority->census.generation ||
			cursor->volume_serial != inspection->volume_serial ||
			!cursor->next_batch_ordinal || !cursor->operations_completed ||
			memcmp(cursor->descriptor_manifest_hash,
				inspection->descriptor_manifest_hash, 32) ||
			memcmp(cursor->mapping_hash, inspection->mapping_hash, 32) ||
			memcmp(cursor->expected_state_hash, state_hash, 32))
		return 0;
	rh_secure_batch_cursor_hash(cursor, seal);
	return !memcmp(seal, cursor->seal, 32);
}

#ifdef ROOTHEALTH_TESTING
static size_t rh_secure_test_batch_max_operations =
	RH_SECURE_BATCH_MAX_OPERATIONS;

void rh_secure_test_set_batch_max_operations(size_t maximum_operations)
{
	if (!maximum_operations ||
			maximum_operations > RH_SECURE_BATCH_MAX_OPERATIONS)
		rh_secure_test_batch_max_operations =
			RH_SECURE_BATCH_MAX_OPERATIONS;
	else
		rh_secure_test_batch_max_operations = maximum_operations;
}
#endif

static size_t rh_secure_batch_max_operations(void)
{
#ifdef ROOTHEALTH_TESTING
	return rh_secure_test_batch_max_operations;
#else
	return RH_SECURE_BATCH_MAX_OPERATIONS;
#endif
}

static enum rh_secure_stage_result rh_secure_stage_index(
		struct rh_ntfs_overlay *overlay,
		const struct rh_secure_inspection *inspection, int sdh,
		size_t maximum_operations, size_t *operation_count, int *more_work)
{
	struct rh_secure_index_action action;
	struct rh_overlay_action_expectation expectation;
	struct rh_secure_overlay_operations_context context;
	enum rh_write_kind kind = sdh ? RH_WRITE_SECURE_SDH : RH_WRITE_SECURE_SII;
	enum rh_secure_stage_result result = RH_SECURE_STAGE_ERROR;
	size_t take;

	memset(&action, 0, sizeof(action));
	memset(&context, 0, sizeof(context));
	if (more_work)
		*more_work = 0;
	if (!operation_count || !maximum_operations ||
			rh_secure_index_prepare_action(overlay->volume,
			inspection, sdh, &action) || !action.count) {
		result = RH_SECURE_STAGE_REFUSED;
		goto out;
	}
	take = action.count;
	if (take > maximum_operations) {
		if (more_work)
			*more_work = 1;
		take = maximum_operations;
	}
	expectation.kind = kind;
	expectation.writes = action.writes;
	expectation.write_count = take;
	context.operations = action.operations;
	context.count = take;
	if (rh_ntfs_overlay_run_action(overlay, &expectation,
			rh_secure_overlay_apply_operations, &context) !=
			RH_OVERLAY_ACTION_OK)
		goto out;
	*operation_count = take;
	result = RH_SECURE_STAGE_PLANNED;
out:
	rh_secure_index_action_destroy(&action);
	return result;
}

enum rh_secure_stage_result rh_secure_stage(struct rh_ntfs_overlay *overlay,
		const struct rh_secure_authority *authority,
		struct rh_secure_plan *plan)
{
	struct rh_secure_inspection inspection;
	struct rh_overlay_expected_write *writes = NULL;
	const unsigned char **bytes = NULL;
	struct rh_overlay_action_expectation expectation;
	struct rh_secure_overlay_data_context context;
	unsigned char plan_hash[32], manifest[32], mapping[32];
	size_t checkpoint, count = 0;
	enum rh_secure_stage_result result = RH_SECURE_STAGE_ERROR;

	memset(&inspection, 0, sizeof(inspection));
	if (!overlay || !overlay->volume || !overlay->writer || !authority ||
			!plan || !rh_secure_census_valid(&authority->census) ||
			authority->census.view != RH_SECURE_PRETRANSACTION) {
		errno = EPERM;
		return RH_SECURE_STAGE_REFUSED;
	}
	memset(plan, 0, sizeof(*plan));
	checkpoint = rh_writer_plan_checkpoint(overlay->writer);
	plan->initial_checkpoint = checkpoint;
	if (rh_secure_inspect(overlay->volume, overlay->writer,
			&authority->census, &inspection)) {
		result = errno == EIO || errno == ENOMEM || errno == EOVERFLOW ?
			RH_SECURE_STAGE_ERROR : RH_SECURE_STAGE_REFUSED;
		goto out;
	}
	if (!rh_secure_authority_valid(authority, RH_SECURE_PRETRANSACTION,
			inspection.volume_serial, inspection.descriptor_manifest_hash)) {
		errno = EPERM;
		result = RH_SECURE_STAGE_REFUSED;
		goto out;
	}
	plan->generation = authority->census.generation;
	plan->volume_serial = inspection.volume_serial;
	if (checkpoint == SIZE_MAX) {
		errno = EOVERFLOW;
		goto out;
	}
	plan->first_operation_ordinal = checkpoint + 1U;
	memcpy(plan->descriptor_manifest_hash,
		inspection.descriptor_manifest_hash, 32);
	memcpy(manifest, inspection.descriptor_manifest_hash, 32);
	memcpy(mapping, inspection.mapping_hash, 32);
	rh_secure_evidence_hash(authority, &inspection, plan->pre_evidence_hash);
	if (!inspection.sds_clean) {
		if (rh_secure_build_sds_writes(&inspection, &writes, &bytes, &count))
			goto out;
		expectation.kind = RH_WRITE_SECURE_SDS;
		expectation.writes = writes;
		expectation.write_count = count;
		context.writes = writes;
		context.bytes = bytes;
		context.count = count;
		if (rh_ntfs_overlay_run_action(overlay, &expectation,
				rh_secure_overlay_apply_data, &context) != RH_OVERLAY_ACTION_OK)
			goto out;
		plan->sds_operation_count = count;
		free(writes);
		free((void *)bytes);
		writes = NULL;
		bytes = NULL;
		count = 0;
		rh_secure_inspection_destroy(&inspection);
		if (rh_secure_inspect(overlay->volume, overlay->writer,
				&authority->census, &inspection) ||
				!inspection.sds_clean ||
				memcmp(manifest, inspection.descriptor_manifest_hash, 32) ||
				memcmp(mapping, inspection.mapping_hash, 32))
			goto out;
	}
	if (!inspection.sdh_clean) {
		result = rh_secure_stage_index(overlay, &inspection, 1, SIZE_MAX,
			&plan->sdh_operation_count, NULL);
		if (result != RH_SECURE_STAGE_PLANNED)
			goto out;
		rh_secure_inspection_destroy(&inspection);
		result = RH_SECURE_STAGE_ERROR;
		if (rh_secure_inspect(overlay->volume, overlay->writer,
				&authority->census, &inspection) ||
				!inspection.sds_clean || !inspection.sdh_clean ||
				memcmp(manifest, inspection.descriptor_manifest_hash, 32) ||
				memcmp(mapping, inspection.mapping_hash, 32))
			goto out;
	}
	if (!inspection.sii_clean) {
		result = rh_secure_stage_index(overlay, &inspection, 0, SIZE_MAX,
			&plan->sii_operation_count, NULL);
		if (result != RH_SECURE_STAGE_PLANNED)
			goto out;
		rh_secure_inspection_destroy(&inspection);
		result = RH_SECURE_STAGE_ERROR;
		if (rh_secure_inspect(overlay->volume, overlay->writer,
				&authority->census, &inspection) ||
				!inspection.sds_clean || !inspection.sdh_clean ||
				!inspection.sii_clean ||
				memcmp(manifest, inspection.descriptor_manifest_hash, 32) ||
				memcmp(mapping, inspection.mapping_hash, 32))
			goto out;
	}
	plan->final_checkpoint = overlay->writer->operation_count;
	if (plan->final_checkpoint < checkpoint)
		goto out;
	plan->operation_count = plan->final_checkpoint - checkpoint;
	if (!plan->operation_count) {
		plan->clean = 1;
		result = RH_SECURE_STAGE_CLEAN;
		goto out;
	}
	if (plan->sds_operation_count > plan->operation_count ||
			plan->sdh_operation_count >
				plan->operation_count - plan->sds_operation_count ||
			plan->sii_operation_count != plan->operation_count -
				plan->sds_operation_count - plan->sdh_operation_count ||
			rh_writer_plan_hash(overlay->writer,
				overlay->writer->operation_count, plan_hash))
		goto out;
	memcpy(plan->staged_plan_hash, plan_hash, 32);
	result = RH_SECURE_STAGE_PLANNED;
out:
	free(writes);
	free((void *)bytes);
	rh_secure_inspection_destroy(&inspection);
	if (result == RH_SECURE_STAGE_ERROR ||
			(result == RH_SECURE_STAGE_REFUSED &&
			 overlay->writer->operation_count != checkpoint)) {
		if (rh_writer_discard_after(overlay->writer, checkpoint))
			overlay->failed = 1;
		memset(plan, 0, sizeof(*plan));
	}
	if (result == RH_SECURE_STAGE_ERROR && !errno)
		errno = EIO;
	return result;
}

enum rh_secure_stage_result rh_secure_stage_batch(
		struct rh_ntfs_overlay *overlay,
		const struct rh_secure_authority *authority,
		const struct rh_secure_batch_cursor *before,
		struct rh_secure_batch_cursor *after, struct rh_secure_plan *plan)
{
	struct rh_secure_inspection inspection;
	struct rh_overlay_expected_write *writes = NULL;
	const unsigned char **bytes = NULL;
	struct rh_overlay_action_expectation expectation;
	struct rh_secure_overlay_data_context data_context;
	unsigned char pre_state[32], staged_state[32], plan_hash[32];
	size_t checkpoint, budget = rh_secure_batch_max_operations();
	size_t count = 0, take;
	uint64_t batch_ordinal = 0, operations_completed = 0;
	int partial = 0;
	enum rh_secure_stage_result result = RH_SECURE_STAGE_ERROR;

	memset(&inspection, 0, sizeof(inspection));
	if (!overlay || !overlay->volume || !overlay->writer || !authority ||
			!before || !after || !plan ||
			!rh_secure_census_valid(&authority->census) ||
			authority->census.view != RH_SECURE_PRETRANSACTION) {
		errno = EPERM;
		return RH_SECURE_STAGE_REFUSED;
	}
	memset(after, 0, sizeof(*after));
	memset(plan, 0, sizeof(*plan));
	checkpoint = rh_writer_plan_checkpoint(overlay->writer);
	plan->initial_checkpoint = checkpoint;
	if (checkpoint == SIZE_MAX)
		goto out;
	if (rh_secure_inspect(overlay->volume, overlay->writer,
			&authority->census, &inspection)) {
		result = errno == EIO || errno == ENOMEM || errno == EOVERFLOW ?
			RH_SECURE_STAGE_ERROR : RH_SECURE_STAGE_REFUSED;
		goto out;
	}
	if (!rh_secure_authority_valid(authority, RH_SECURE_PRETRANSACTION,
			inspection.volume_serial, inspection.descriptor_manifest_hash)) {
		errno = EPERM;
		result = RH_SECURE_STAGE_REFUSED;
		goto out;
	}
	rh_secure_state_hash(&inspection, pre_state);
	if (!rh_secure_batch_cursor_empty(before)) {
		if (!rh_secure_batch_cursor_valid(before, authority, &inspection,
				pre_state)) {
			errno = ESTALE;
			result = RH_SECURE_STAGE_REFUSED;
			goto out;
		}
		batch_ordinal = before->next_batch_ordinal;
		operations_completed = before->operations_completed;
	}
	plan->batch = 1;
	plan->batch_ordinal = batch_ordinal;
	plan->generation = authority->census.generation;
	plan->volume_serial = inspection.volume_serial;
	plan->first_operation_ordinal = checkpoint + 1U;
	memcpy(plan->descriptor_manifest_hash,
		inspection.descriptor_manifest_hash, 32);
	memcpy(plan->mapping_hash, inspection.mapping_hash, 32);
	memcpy(plan->pre_state_hash, pre_state, 32);
	rh_secure_evidence_hash(authority, &inspection, plan->pre_evidence_hash);

	if (!inspection.sds_clean) {
		if (rh_secure_build_sds_writes(&inspection, &writes, &bytes, &count))
			goto out;
		take = count > budget ? budget : count;
		expectation.kind = RH_WRITE_SECURE_SDS;
		expectation.writes = writes;
		expectation.write_count = take;
		data_context.writes = writes;
		data_context.bytes = bytes;
		data_context.count = take;
		if (rh_ntfs_overlay_run_action(overlay, &expectation,
				rh_secure_overlay_apply_data, &data_context) !=
				RH_OVERLAY_ACTION_OK)
			goto out;
		plan->sds_operation_count = take;
		budget -= take;
		partial = take != count;
		free(writes);
		free((void *)bytes);
		writes = NULL;
		bytes = NULL;
		count = 0;
		if (partial)
			goto staged;
		rh_secure_inspection_destroy(&inspection);
		if (rh_secure_inspect(overlay->volume, overlay->writer,
				&authority->census, &inspection) || !inspection.sds_clean ||
				memcmp(plan->descriptor_manifest_hash,
					inspection.descriptor_manifest_hash, 32) ||
				memcmp(plan->mapping_hash, inspection.mapping_hash, 32))
			goto out;
	}
	if (budget && !inspection.sdh_clean) {
		result = rh_secure_stage_index(overlay, &inspection, 1, budget,
			&plan->sdh_operation_count, &partial);
		if (result != RH_SECURE_STAGE_PLANNED)
			goto out;
		budget -= plan->sdh_operation_count;
		if (partial)
			goto staged;
		rh_secure_inspection_destroy(&inspection);
		result = RH_SECURE_STAGE_ERROR;
		if (rh_secure_inspect(overlay->volume, overlay->writer,
				&authority->census, &inspection) || !inspection.sds_clean ||
				!inspection.sdh_clean ||
				memcmp(plan->descriptor_manifest_hash,
					inspection.descriptor_manifest_hash, 32) ||
				memcmp(plan->mapping_hash, inspection.mapping_hash, 32))
			goto out;
	}
	if (budget && !inspection.sii_clean) {
		result = rh_secure_stage_index(overlay, &inspection, 0, budget,
			&plan->sii_operation_count, &partial);
		if (result != RH_SECURE_STAGE_PLANNED)
			goto out;
		budget -= plan->sii_operation_count;
	}
staged:
	rh_secure_inspection_destroy(&inspection);
	result = RH_SECURE_STAGE_ERROR;
	if (rh_secure_inspect(overlay->volume, overlay->writer,
			&authority->census, &inspection) ||
			memcmp(plan->descriptor_manifest_hash,
				inspection.descriptor_manifest_hash, 32) ||
			memcmp(plan->mapping_hash, inspection.mapping_hash, 32))
		goto out;
	plan->more_work = !inspection.sds_clean || !inspection.sdh_clean ||
		!inspection.sii_clean;
	plan->final_checkpoint = overlay->writer->operation_count;
	if (plan->final_checkpoint < checkpoint)
		goto out;
	plan->operation_count = plan->final_checkpoint - checkpoint;
	if (!plan->operation_count) {
		if (plan->more_work) {
			errno = EIO;
			goto out;
		}
		plan->clean = 1;
		result = RH_SECURE_STAGE_CLEAN;
	} else {
		if (plan->operation_count > rh_secure_batch_max_operations() ||
				plan->sds_operation_count > plan->operation_count ||
				plan->sdh_operation_count > plan->operation_count -
					plan->sds_operation_count ||
				plan->sii_operation_count != plan->operation_count -
					plan->sds_operation_count - plan->sdh_operation_count ||
				rh_writer_plan_hash(overlay->writer,
					overlay->writer->operation_count, plan_hash))
			goto out;
		memcpy(plan->staged_plan_hash, plan_hash, 32);
		result = RH_SECURE_STAGE_PLANNED;
	}
	rh_secure_state_hash(&inspection, staged_state);
	memcpy(plan->staged_state_hash, staged_state, 32);
	after->version = RH_SECURE_BATCH_CURSOR_VERSION;
	after->complete = !plan->more_work;
	after->generation = plan->generation;
	after->volume_serial = plan->volume_serial;
	after->next_batch_ordinal = batch_ordinal + 1U;
	if (operations_completed > UINT64_MAX - plan->operation_count) {
		errno = EOVERFLOW;
		result = RH_SECURE_STAGE_ERROR;
		goto out;
	}
	after->operations_completed = operations_completed + plan->operation_count;
	memcpy(after->descriptor_manifest_hash,
		plan->descriptor_manifest_hash, 32);
	memcpy(after->mapping_hash, plan->mapping_hash, 32);
	memcpy(after->expected_state_hash, staged_state, 32);
	rh_secure_batch_cursor_hash(after, after->seal);
out:
	free(writes);
	free((void *)bytes);
	rh_secure_inspection_destroy(&inspection);
	if (result == RH_SECURE_STAGE_ERROR ||
			(result == RH_SECURE_STAGE_REFUSED &&
			 overlay->writer->operation_count != checkpoint)) {
		if (rh_writer_discard_after(overlay->writer, checkpoint))
			overlay->failed = 1;
		memset(after, 0, sizeof(*after));
		memset(plan, 0, sizeof(*plan));
	}
	if (result == RH_SECURE_STAGE_ERROR && !errno)
		errno = EIO;
	return result;
}

static int rh_secure_target_core_equal(
		const struct rh_write_semantic_target *actual,
		const struct rh_write_semantic_target *expected)
{
	return actual && expected &&
		actual->seal_version == expected->seal_version &&
		actual->object == expected->object &&
		actual->owner_mft_record == expected->owner_mft_record &&
		actual->owner_sequence == expected->owner_sequence &&
		actual->attribute_instance == expected->attribute_instance &&
		actual->attribute_type == expected->attribute_type &&
		actual->attribute_name_length == expected->attribute_name_length &&
		actual->flags == expected->flags &&
		!memcmp(actual->attribute_name_hash, expected->attribute_name_hash, 32) &&
		actual->lowest_vcn == expected->lowest_vcn &&
		actual->logical_vcn == expected->logical_vcn &&
		actual->logical_offset == expected->logical_offset &&
		actual->logical_length == expected->logical_length &&
		actual->semantic_target_offset ==
			expected->semantic_target_offset &&
		actual->semantic_target_length ==
			expected->semantic_target_length &&
		actual->lcn == expected->lcn;
}

static int rh_secure_plan_shape_valid(const struct rh_writer *writer,
		const struct rh_secure_plan *plan)
{
	return writer && plan && !plan->clean && !plan->finalized &&
		plan->generation && plan->volume_serial &&
		plan->initial_checkpoint < SIZE_MAX &&
		plan->first_operation_ordinal == plan->initial_checkpoint + 1U &&
		plan->final_checkpoint == writer->operation_count &&
		plan->final_checkpoint >= plan->initial_checkpoint &&
		plan->operation_count ==
			plan->final_checkpoint - plan->initial_checkpoint &&
		plan->sds_operation_count <= plan->operation_count &&
		plan->sdh_operation_count <=
			plan->operation_count - plan->sds_operation_count &&
		plan->sii_operation_count == plan->operation_count -
			plan->sds_operation_count - plan->sdh_operation_count &&
		plan->operation_count &&
		!rh_secure_all_zero(plan->descriptor_manifest_hash, 32) &&
		!rh_secure_all_zero(plan->pre_evidence_hash, 32) &&
		!rh_secure_all_zero(plan->staged_plan_hash, 32);
}

static int rh_secure_slice_for_logical(
		const struct rh_secure_inspection *inspection, uint64_t logical,
		uint64_t length, const struct rh_secure_mapping_slice **slice_out,
		uint64_t *relative_out)
{
	size_t i;

	if (!inspection || !slice_out || !relative_out || !length ||
			logical > UINT64_MAX - length)
		return -1;
	for (i = 0; i < inspection->sds_slice_count; i++) {
		const struct rh_secure_mapping_slice *slice =
			&inspection->sds_slices[i];

		if (logical < slice->logical_offset ||
				logical - slice->logical_offset > slice->length ||
				length > slice->length - (logical - slice->logical_offset))
			continue;
		*slice_out = slice;
		*relative_out = logical - slice->logical_offset;
		return 0;
	}
	return -1;
}

static int rh_secure_validate_sds_plan(
		const struct rh_secure_inspection *staged,
		const struct rh_writer *writer, const struct rh_secure_plan *plan,
		const struct rh_secure_census *census)
{
	struct rh_secure_inspection original;
	struct rh_overlay_expected_write *expected = NULL;
	const unsigned char **expected_bytes = NULL;
	unsigned char *original_bytes = NULL;
	size_t expected_count = 0, i;
	int result = -1;

	if (!plan->sds_operation_count)
		return 0;
	memset(&original, 0, sizeof(original));
	original_bytes = malloc(staged->sds_data_size);
	original.sds_staged = malloc(staged->sds_data_size);
	if (staged->sds_slice_count >
			SIZE_MAX / sizeof(*original.sds_slices)) {
		errno = EOVERFLOW;
		goto out;
	}
	original.sds_slices = malloc(staged->sds_slice_count *
		sizeof(*original.sds_slices));
	if (!original_bytes || !original.sds_staged || !original.sds_slices)
		goto out;
	memcpy(original_bytes, staged->sds_current, staged->sds_data_size);
	memcpy(original.sds_slices, staged->sds_slices,
		staged->sds_slice_count * sizeof(*original.sds_slices));
	original.sds_current = original_bytes;
	original.sds_data_size = staged->sds_data_size;
	original.sds_slice_count = staged->sds_slice_count;
	original.owner_mft_record = staged->owner_mft_record;
	original.owner_sequence = staged->owner_sequence;
	original.sds_instance = staged->sds_instance;
	for (i = 0; i < plan->sds_operation_count; i++) {
		const struct rh_write_operation *operation =
			&writer->operations[plan->initial_checkpoint + i];
		const struct rh_secure_mapping_slice *slice;
		struct rh_write_semantic_target target;
		uint64_t relative;

		if (operation->kind != RH_WRITE_SECURE_SDS ||
				!rh_write_operation_semantics_valid(operation, 0) ||
				rh_secure_slice_for_logical(staged,
					operation->target.logical_offset, operation->length,
					&slice, &relative))
			goto out;
		rh_secure_nonresident_target(staged, slice, relative,
			operation->length, &target);
		if (!rh_secure_target_core_equal(&operation->target, &target) ||
				memcmp(operation->after,
					staged->sds_current + operation->target.logical_offset,
					operation->length))
			goto out;
		memcpy(original_bytes + operation->target.logical_offset,
			operation->before, operation->length);
	}
	memcpy(original.sds_staged, original.sds_current,
		original.sds_data_size);
	if (rh_secure_reconcile_sds(&original, census->live_security_ids,
			census->live_security_id_count) ||
			rh_secure_build_manifest(&original) ||
			memcmp(original.descriptor_manifest_hash,
				plan->descriptor_manifest_hash, 32) ||
			rh_secure_build_sds_writes(&original, &expected,
				&expected_bytes, &expected_count) ||
			expected_count < plan->sds_operation_count)
		goto out;
	for (i = 0; i < plan->sds_operation_count; i++) {
		const struct rh_write_operation *operation =
			&writer->operations[plan->initial_checkpoint + i];

		if (operation->offset != expected[i].offset ||
				operation->length != expected[i].length ||
				!rh_secure_target_core_equal(&operation->target,
					&expected[i].target) ||
				memcmp(operation->before,
					original.sds_current +
						expected[i].target.logical_offset,
					operation->length) ||
				memcmp(operation->after, expected_bytes[i], operation->length))
			goto out;
	}
	result = 0;
out:
	free(expected);
	free((void *)expected_bytes);
	free(original.descriptors);
	free(original.sds_slices);
	free(original.sds_staged);
	free(original_bytes);
	return result;
}

static int rh_secure_expected_before(const struct rh_writer *prefix,
		const struct rh_secure_index_action *action, size_t current,
		unsigned char *before)
{
	const struct rh_overlay_expected_write *write = &action->writes[current];
	size_t i;

	if (rh_writer_read((struct rh_writer *)prefix, write->offset,
			(size_t)write->length, before))
		return -1;
	for (i = 0; i < current; i++) {
		const struct rh_overlay_expected_write *prior = &action->writes[i];
		uint64_t start, end, prior_end;

		if (write->offset > UINT64_MAX - write->length ||
				prior->offset > UINT64_MAX - prior->length)
			return -1;
		end = write->offset + write->length;
		prior_end = prior->offset + prior->length;
		start = write->offset > prior->offset ? write->offset : prior->offset;
		if (start >= end || start >= prior_end)
			continue;
		end = end < prior_end ? end : prior_end;
		memcpy(before + (size_t)(start - write->offset),
			action->expected_after[i] + (size_t)(start - prior->offset),
			(size_t)(end - start));
	}
	return 0;
}

static int rh_secure_validate_index_plan(
		const struct rh_secure_inspection *staged,
		const struct rh_writer *writer, const struct rh_secure_plan *plan,
		const struct rh_secure_census *census)
{
	size_t cursor = plan->initial_checkpoint + plan->sds_operation_count;
	int which;

	for (which = 0; which < 2; which++) {
		int sdh = which == 0;
		size_t expected_count = sdh ? plan->sdh_operation_count :
			plan->sii_operation_count;
		struct rh_writer prefix;
		struct rh_ntfs_overlay prefix_overlay;
		struct rh_secure_inspection inspection;
		struct rh_secure_index_action action;
		int mounted = 0;
		size_t i;
		int valid = -1;

		if (!expected_count)
			continue;
		memset(&inspection, 0, sizeof(inspection));
		memset(&action, 0, sizeof(action));
		prefix = *writer;
		prefix.operation_count = cursor;
		if (rh_ntfs_overlay_mount(&prefix_overlay, &prefix, 0))
			goto action_out;
		mounted = 1;
		if (rh_secure_inspect(prefix_overlay.volume, &prefix, census,
				&inspection) || inspection.volume_serial != staged->volume_serial ||
				memcmp(inspection.descriptor_manifest_hash,
					staged->descriptor_manifest_hash, 32) ||
				rh_secure_index_prepare_action(prefix_overlay.volume, &inspection,
					sdh, &action) || action.count < expected_count ||
				cursor > writer->operation_count ||
				expected_count > writer->operation_count - cursor)
			goto action_out;
		for (i = 0; i < expected_count; i++) {
			const struct rh_write_operation *operation =
				&writer->operations[cursor + i];
			unsigned char *before = malloc((size_t)action.writes[i].length);

			if (!before || rh_secure_expected_before(&prefix, &action, i,
					before) || operation->kind != (sdh ?
					RH_WRITE_SECURE_SDH : RH_WRITE_SECURE_SII) ||
					operation->offset != action.writes[i].offset ||
					operation->length != action.writes[i].length ||
					!rh_secure_target_core_equal(&operation->target,
						&action.writes[i].target) ||
					!rh_write_operation_semantics_valid(operation, 0) ||
					memcmp(operation->before, before, operation->length) ||
					memcmp(operation->after, action.expected_after[i],
						operation->length) ||
					!memcmp(operation->target.semantic_before_hash,
						operation->target.semantic_after_hash, 32)) {
				free(before);
				goto action_out;
			}
			free(before);
		}
		valid = 0;
action_out:
		rh_secure_index_action_destroy(&action);
		rh_secure_inspection_destroy(&inspection);
		if (mounted)
			rh_ntfs_overlay_unmount(&prefix_overlay);
		if (valid)
			return -1;
		cursor += expected_count;
	}
	return cursor == plan->final_checkpoint ? 0 : -1;
}

int rh_secure_verify_staged(struct rh_ntfs_overlay *overlay,
		const struct rh_secure_authority *authority,
		struct rh_secure_plan *plan)
{
	struct rh_secure_inspection inspection;
	unsigned char plan_hash[32];
	int result = -1;

	memset(&inspection, 0, sizeof(inspection));
	if (!overlay || !overlay->volume || !overlay->writer || !authority ||
			!plan || plan->staged_verified ||
			!rh_secure_plan_shape_valid(overlay->writer, plan) ||
			authority->census.view != RH_SECURE_STAGED ||
			authority->census.generation != plan->generation ||
			rh_writer_plan_hash(overlay->writer,
				overlay->writer->operation_count, plan_hash) ||
			memcmp(plan_hash, plan->staged_plan_hash, 32)) {
		errno = EPERM;
		return -1;
	}
	if (rh_secure_inspect(overlay->volume, overlay->writer,
			&authority->census, &inspection) ||
			!inspection.sds_clean || !inspection.sdh_clean ||
			!inspection.sii_clean ||
			inspection.volume_serial != plan->volume_serial ||
			memcmp(inspection.descriptor_manifest_hash,
				plan->descriptor_manifest_hash, 32) ||
			!rh_secure_authority_valid(authority, RH_SECURE_STAGED,
				inspection.volume_serial,
				inspection.descriptor_manifest_hash) ||
			rh_secure_validate_sds_plan(&inspection, overlay->writer, plan,
				&authority->census) ||
			rh_secure_validate_index_plan(&inspection, overlay->writer, plan,
				&authority->census))
		goto out;
	rh_secure_evidence_hash(authority, &inspection,
		plan->staged_evidence_hash);
	if (rh_secure_all_zero(plan->staged_evidence_hash, 32))
		goto out;
	plan->staged_verified = 1;
	result = 0;
out:
	rh_secure_inspection_destroy(&inspection);
	if (result && !errno)
		errno = EPERM;
	return result;
}

int rh_secure_verify_batch_staged(struct rh_ntfs_overlay *overlay,
		const struct rh_secure_authority *authority,
		const struct rh_secure_batch_cursor *after,
		struct rh_secure_plan *plan)
{
	struct rh_secure_inspection inspection;
	unsigned char plan_hash[32], state_hash[32], cursor_seal[32];
	int clean, result = -1;

	memset(&inspection, 0, sizeof(inspection));
	if (!overlay || !overlay->volume || !overlay->writer || !authority ||
			!after || !plan || !plan->batch || plan->staged_verified ||
			!rh_secure_plan_shape_valid(overlay->writer, plan) ||
			authority->census.view != RH_SECURE_STAGED ||
			authority->census.generation != plan->generation ||
			after->version != RH_SECURE_BATCH_CURSOR_VERSION ||
			after->generation != plan->generation ||
			after->volume_serial != plan->volume_serial ||
			after->next_batch_ordinal != plan->batch_ordinal + 1U ||
			after->operations_completed < plan->operation_count ||
			!!after->complete == !!plan->more_work ||
			memcmp(after->descriptor_manifest_hash,
				plan->descriptor_manifest_hash, 32) ||
			memcmp(after->mapping_hash, plan->mapping_hash, 32) ||
			memcmp(after->expected_state_hash, plan->staged_state_hash, 32) ||
			rh_writer_plan_hash(overlay->writer,
				overlay->writer->operation_count, plan_hash) ||
			memcmp(plan_hash, plan->staged_plan_hash, 32)) {
		errno = EPERM;
		return -1;
	}
	rh_secure_batch_cursor_hash(after, cursor_seal);
	if (memcmp(cursor_seal, after->seal, 32)) {
		errno = EPERM;
		return -1;
	}
	if (rh_secure_inspect(overlay->volume, overlay->writer,
			&authority->census, &inspection) ||
			inspection.volume_serial != plan->volume_serial ||
			memcmp(inspection.descriptor_manifest_hash,
				plan->descriptor_manifest_hash, 32) ||
			memcmp(inspection.mapping_hash, plan->mapping_hash, 32) ||
			!rh_secure_authority_valid(authority, RH_SECURE_STAGED,
				inspection.volume_serial,
				inspection.descriptor_manifest_hash) ||
			rh_secure_validate_sds_plan(&inspection, overlay->writer, plan,
				&authority->census) ||
			rh_secure_validate_index_plan(&inspection, overlay->writer, plan,
				&authority->census))
		goto out;
	clean = inspection.sds_clean && inspection.sdh_clean &&
		inspection.sii_clean;
	if (clean == !!plan->more_work)
		goto out;
	rh_secure_state_hash(&inspection, state_hash);
	if (memcmp(state_hash, plan->staged_state_hash, 32))
		goto out;
	rh_secure_evidence_hash(authority, &inspection,
		plan->staged_evidence_hash);
	if (rh_secure_all_zero(plan->staged_evidence_hash, 32))
		goto out;
	plan->staged_verified = 1;
	result = 0;
out:
	rh_secure_inspection_destroy(&inspection);
	if (result && !errno)
		errno = EPERM;
	return result;
}

int rh_secure_finalize(struct rh_writer *writer, struct rh_secure_plan *plan)
{
	struct rh_write_semantic_target *saved = NULL;
	unsigned char plan_hash[32];
	size_t i;

	if (!writer || !plan || !plan->staged_verified || plan->finalized ||
			!rh_secure_plan_shape_valid(writer, plan) ||
			rh_secure_all_zero(plan->staged_evidence_hash, 32) ||
			rh_writer_plan_hash(writer, writer->operation_count, plan_hash) ||
			memcmp(plan_hash, plan->staged_plan_hash, 32)) {
		errno = EPERM;
		return -1;
	}
	for (i = plan->initial_checkpoint; i < plan->final_checkpoint; i++)
		if (!rh_write_operation_semantics_valid(&writer->operations[i], 0)) {
			errno = EPERM;
			return -1;
		}
	if (plan->operation_count > SIZE_MAX / sizeof(*saved)) {
		errno = EOVERFLOW;
		return -1;
	}
	saved = malloc(plan->operation_count * sizeof(*saved));
	if (!saved)
		return -1;
	for (i = 0; i < plan->operation_count; i++)
		saved[i] = writer->operations[plan->initial_checkpoint + i].target;
	for (i = plan->initial_checkpoint; i < plan->final_checkpoint; i++)
		if (rh_writer_finalize_target(writer, i + 1U,
				RH_SECURE_EVIDENCE_VERSION, plan->generation,
				plan->pre_evidence_hash, plan->staged_evidence_hash))
			goto rollback;
	for (i = plan->initial_checkpoint; i < plan->final_checkpoint; i++)
		if (!rh_write_operation_semantics_valid(&writer->operations[i], 1))
			goto rollback;
	free(saved);
	plan->finalized = 1;
	return 0;
rollback:
	for (i = 0; i < plan->operation_count; i++)
		writer->operations[plan->initial_checkpoint + i].target = saved[i];
	free(saved);
	plan->finalized = 0;
	if (!errno)
		errno = EIO;
	return -1;
}

static int rh_secure_recovery_evidence_valid(
		const struct rh_secure_recovery_entry *entry, enum rh_write_kind kind,
		const struct rh_write_semantic_target *expected, uint64_t generation,
		const unsigned char pre_evidence[32],
		const unsigned char staged_evidence[32])
{
	return entry && entry->kind == kind &&
		entry->length &&
		rh_secure_target_core_equal(&entry->target, expected) &&
		entry->target.finalized &&
		entry->target.evidence_version == RH_SECURE_EVIDENCE_VERSION &&
		entry->target.evidence_generation == generation &&
		!memcmp(entry->target.evidence_hash, pre_evidence, 32) &&
		!memcmp(entry->target.staged_view_hash, staged_evidence, 32) &&
		rh_write_semantic_target_valid(kind, &entry->target,
			entry->target_offset, entry->length, 1);
}

static int rh_secure_recovery_hashes(
		const struct rh_secure_recovery_entry *entry,
		const unsigned char *before, const unsigned char *after)
{
	unsigned char before_hash[32], after_hash[32];

	rh_sha256(before, entry->length, before_hash);
	rh_sha256(after, entry->length, after_hash);
	return !memcmp(before_hash, entry->old_hash, 32) &&
		!memcmp(after_hash, entry->new_hash, 32);
}

static int rh_secure_rederive_sds_recovery(
		const struct rh_secure_inspection *pre,
		const struct rh_secure_inspection *post,
		const struct rh_secure_recovery_entry *entries, size_t entry_count,
		uint64_t generation, const unsigned char pre_evidence[32],
		const unsigned char staged_evidence[32], size_t *used)
{
	struct rh_overlay_expected_write *expected = NULL;
	const unsigned char **bytes = NULL;
	size_t count = 0, i;
	int result = -1;

	*used = 0;
	if (pre->sds_clean)
		return !memcmp(pre->sds_current, post->sds_current,
			pre->sds_data_size) ? 0 : -1;
	if (rh_secure_build_sds_writes(pre, &expected, &bytes, &count) ||
			count > entry_count)
		goto out;
	for (i = 0; i < count; i++) {
		const struct rh_secure_recovery_entry *entry = &entries[i];
		const unsigned char *before = pre->sds_current +
			expected[i].target.logical_offset;
		const unsigned char *after = bytes[i];

		if (entry->target_offset != expected[i].offset ||
				entry->length != expected[i].length ||
				!rh_secure_recovery_evidence_valid(entry,
					RH_WRITE_SECURE_SDS, &expected[i].target, generation,
					pre_evidence, staged_evidence) ||
				!rh_secure_recovery_hashes(entry, before, after) ||
				memcmp(after, post->sds_current +
					expected[i].target.logical_offset, entry->length) ||
				memcmp(entry->target.semantic_before_hash,
					entry->old_hash, 32) ||
				memcmp(entry->target.semantic_after_hash,
					entry->new_hash, 32))
			goto out;
	}
	*used = count;
	result = 0;
out:
	free(expected);
	free((void *)bytes);
	return result;
}

static int rh_secure_rederive_index_recovery(ntfs_volume *pre_volume,
		struct rh_writer *pre_writer, struct rh_writer *post_writer,
		const struct rh_secure_inspection *pre,
		const struct rh_secure_inspection *post,
		const struct rh_secure_census *census,
		const struct rh_secure_recovery_entry *entries, size_t entry_count,
		uint64_t generation, const unsigned char pre_evidence[32],
		const unsigned char staged_evidence[32])
{
	struct rh_writer prefix;
	size_t cursor = 0, i;
	int which, result = -1;

	(void)pre_volume;
	(void)post;
	prefix = *pre_writer;
	prefix.operations = NULL;
	prefix.operation_count = 0;
	prefix.operation_capacity = 0;
	prefix.planned_bytes = 0;
	prefix.last_verified_ordinal = 0;
	prefix.sync_count = 0;
	prefix.write_boundaries = 0;
	prefix.commit_started = 0;
	prefix.commit_completed = 0;
	prefix.backend = NULL;
	prefix.backend_opaque = NULL;
	for (which = 0; which < 2; which++) {
		int sdh = which == 0;
		int dirty = sdh ? !pre->sdh_clean : !pre->sii_clean;
		struct rh_ntfs_overlay prefix_overlay;
		struct rh_secure_inspection inspection;
		struct rh_secure_index_action action;
		int mounted = 0;

		if (!dirty)
			continue;
		memset(&inspection, 0, sizeof(inspection));
		memset(&action, 0, sizeof(action));
		if (rh_ntfs_overlay_mount(&prefix_overlay, &prefix, 0))
			goto action_out;
		mounted = 1;
		if (rh_secure_inspect(prefix_overlay.volume, &prefix, census,
				&inspection) || inspection.volume_serial != pre->volume_serial ||
				memcmp(inspection.descriptor_manifest_hash,
					pre->descriptor_manifest_hash, 32) ||
				rh_secure_index_prepare_action(prefix_overlay.volume, &inspection,
					sdh, &action) || !action.count ||
				action.count > entry_count - cursor)
			goto action_out;
		for (i = 0; i < action.count; i++) {
			const struct rh_secure_recovery_entry *entry = &entries[cursor + i];
			unsigned char *before = malloc((size_t)action.writes[i].length);
			const struct rh_write_operation *derived;

			if (!before || rh_secure_expected_before(&prefix, &action, i,
					before) || entry->target_offset != action.writes[i].offset ||
					entry->length != action.writes[i].length ||
					!rh_secure_recovery_evidence_valid(entry, sdh ?
						RH_WRITE_SECURE_SDH : RH_WRITE_SECURE_SII,
						&action.writes[i].target, generation, pre_evidence,
						staged_evidence) ||
					!rh_secure_recovery_hashes(entry, before,
						action.expected_after[i]) ||
					rh_writer_plan_typed(&prefix, sdh ? RH_WRITE_SECURE_SDH :
						RH_WRITE_SECURE_SII, action.writes[i].offset,
						(size_t)action.writes[i].length,
						action.expected_after[i], &action.writes[i].target)) {
				free(before);
				goto action_out;
			}
			free(before);
			derived = &prefix.operations[prefix.operation_count - 1U];
			if (memcmp(derived->target.semantic_before_hash,
					entry->target.semantic_before_hash, 32) ||
					memcmp(derived->target.semantic_after_hash,
						entry->target.semantic_after_hash, 32))
				goto action_out;
		}
		cursor += action.count;
		rh_secure_index_action_destroy(&action);
		rh_secure_inspection_destroy(&inspection);
		rh_ntfs_overlay_unmount(&prefix_overlay);
		continue;
action_out:
		rh_secure_index_action_destroy(&action);
		rh_secure_inspection_destroy(&inspection);
		if (mounted)
			rh_ntfs_overlay_unmount(&prefix_overlay);
		goto out;
	}
	if (cursor != entry_count)
		goto out;
	for (i = 0; i < prefix.operation_count; i++) {
		const struct rh_write_operation *operation = &prefix.operations[i];
		unsigned char *actual = malloc(operation->length);

		if (!actual || rh_writer_read(&prefix, operation->offset,
				operation->length, actual) ||
				rh_writer_read(post_writer, operation->offset,
					operation->length, operation->before) ||
				memcmp(actual, operation->before, operation->length)) {
			free(actual);
			goto out;
		}
		free(actual);
	}
	result = 0;
out:
	rh_writer_reset_plan(&prefix);
	return result;
}

int rh_secure_rederive_recovery(ntfs_volume *pre_volume,
		struct rh_writer *pre_writer,
		const struct rh_secure_authority *pre_authority,
		ntfs_volume *post_volume, struct rh_writer *post_writer,
		const struct rh_secure_authority *post_authority,
		const struct rh_secure_recovery_entry *entries, size_t entry_count)
{
	struct rh_secure_inspection pre, post;
	unsigned char pre_evidence[32], staged_evidence[32];
	size_t sds_used = 0;
	int result = -1;

	memset(&pre, 0, sizeof(pre));
	memset(&post, 0, sizeof(post));
	if (!pre_volume || !pre_writer || !pre_authority || !post_volume ||
			!post_writer || !post_authority || !entries || !entry_count ||
			pre_writer->operation_count || post_writer->operation_count ||
			pre_authority->census.view != RH_SECURE_PRETRANSACTION ||
			post_authority->census.view != RH_SECURE_STAGED ||
			pre_authority->census.generation !=
				post_authority->census.generation) {
		errno = EPERM;
		return -1;
	}
	if (rh_secure_inspect(pre_volume, pre_writer, &pre_authority->census,
			&pre) ||
			rh_secure_inspect(post_volume, post_writer,
				&post_authority->census, &post) ||
			pre.volume_serial != post.volume_serial ||
			pre.sds_data_size != post.sds_data_size ||
			pre.mft_record_physical != post.mft_record_physical ||
			pre.sds_instance != post.sds_instance ||
			pre.sdh_instance != post.sdh_instance ||
			pre.sii_instance != post.sii_instance ||
			pre.sdh_semantic_physical != post.sdh_semantic_physical ||
			pre.sii_semantic_physical != post.sii_semantic_physical ||
			memcmp(pre.mapping_hash, post.mapping_hash, 32) ||
			memcmp(pre.descriptor_manifest_hash,
				post.descriptor_manifest_hash, 32) ||
			!post.sds_clean || !post.sdh_clean || !post.sii_clean ||
			memcmp(pre.sds_staged, post.sds_current, pre.sds_data_size) ||
			!rh_secure_authority_valid(pre_authority,
				RH_SECURE_PRETRANSACTION, pre.volume_serial,
				pre.descriptor_manifest_hash) ||
			!rh_secure_authority_valid(post_authority, RH_SECURE_STAGED,
				post.volume_serial, post.descriptor_manifest_hash))
		goto out;
	rh_secure_evidence_hash(pre_authority, &pre, pre_evidence);
	rh_secure_evidence_hash(post_authority, &post, staged_evidence);
	if (rh_secure_rederive_sds_recovery(&pre, &post, entries, entry_count,
			pre_authority->census.generation, pre_evidence,
			staged_evidence, &sds_used) ||
			rh_secure_rederive_index_recovery(pre_volume, pre_writer,
				post_writer, &pre, &post, &pre_authority->census,
				entries + sds_used,
				entry_count - sds_used, pre_authority->census.generation,
				pre_evidence, staged_evidence))
		goto out;
	result = 0;
out:
	rh_secure_inspection_destroy(&post);
	rh_secure_inspection_destroy(&pre);
	if (result && !errno)
		errno = EPERM;
	return result;
}

static int rh_secure_batch_cursor_equal(
		const struct rh_secure_batch_cursor *first,
		const struct rh_secure_batch_cursor *second)
{
	return first && second && first->version == second->version &&
		first->complete == second->complete &&
		first->generation == second->generation &&
		first->volume_serial == second->volume_serial &&
		first->next_batch_ordinal == second->next_batch_ordinal &&
		first->operations_completed == second->operations_completed &&
		!memcmp(first->descriptor_manifest_hash,
			second->descriptor_manifest_hash, 32) &&
		!memcmp(first->mapping_hash, second->mapping_hash, 32) &&
		!memcmp(first->expected_state_hash, second->expected_state_hash, 32) &&
		!memcmp(first->seal, second->seal, 32);
}

static void rh_secure_writer_plan_clone(struct rh_writer *target,
		const struct rh_writer *source)
{
	*target = *source;
	target->operations = NULL;
	target->operation_count = 0;
	target->operation_capacity = 0;
	target->planned_bytes = 0;
	target->last_verified_ordinal = 0;
	target->sync_count = 0;
	target->write_boundaries = 0;
	target->commit_started = 0;
	target->commit_completed = 0;
	target->backend = NULL;
	target->backend_opaque = NULL;
}

int rh_secure_rederive_batch_recovery(ntfs_volume *pre_volume,
		struct rh_writer *pre_writer,
		const struct rh_secure_authority *pre_authority,
		const struct rh_secure_batch_cursor *before,
		ntfs_volume *post_volume, struct rh_writer *post_writer,
		const struct rh_secure_authority *post_authority,
		const struct rh_secure_batch_cursor *after,
		const struct rh_secure_recovery_entry *entries, size_t entry_count)
{
	struct rh_secure_inspection pre, post;
	struct rh_secure_batch_cursor derived_after;
	struct rh_secure_plan derived_plan;
	struct rh_writer derived_writer;
	struct rh_ntfs_overlay derived_overlay;
	unsigned char pre_state[32], post_state[32], staged_evidence[32];
	size_t i = 0;
	int derived_mounted = 0, result = -1;

	memset(&pre, 0, sizeof(pre));
	memset(&post, 0, sizeof(post));
	memset(&derived_after, 0, sizeof(derived_after));
	memset(&derived_plan, 0, sizeof(derived_plan));
	memset(&derived_writer, 0, sizeof(derived_writer));
	memset(&derived_overlay, 0, sizeof(derived_overlay));
	if (!pre_volume || !pre_writer || !pre_authority || !before ||
			!post_volume || !post_writer || !post_authority || !after ||
			!entries || !entry_count ||
			entry_count > RH_SECURE_BATCH_MAX_OPERATIONS ||
			pre_writer->operation_count || post_writer->operation_count ||
			pre_authority->census.view != RH_SECURE_PRETRANSACTION ||
			post_authority->census.view != RH_SECURE_STAGED ||
			pre_authority->census.generation !=
				post_authority->census.generation) {
		errno = EPERM;
		return -1;
	}
	if (rh_secure_inspect(pre_volume, pre_writer, &pre_authority->census,
			&pre) ||
			rh_secure_inspect(post_volume, post_writer,
				&post_authority->census, &post) ||
			pre.volume_serial != post.volume_serial ||
			memcmp(pre.descriptor_manifest_hash,
				post.descriptor_manifest_hash, 32) ||
			memcmp(pre.mapping_hash, post.mapping_hash, 32) ||
			!rh_secure_authority_valid(pre_authority,
				RH_SECURE_PRETRANSACTION, pre.volume_serial,
				pre.descriptor_manifest_hash) ||
			!rh_secure_authority_valid(post_authority, RH_SECURE_STAGED,
				post.volume_serial, post.descriptor_manifest_hash))
		goto out;
	rh_secure_state_hash(&pre, pre_state);
	rh_secure_state_hash(&post, post_state);
	if (memcmp(post_state, after->expected_state_hash, 32) ||
			(after->complete != (unsigned int)(post.sds_clean &&
				post.sdh_clean && post.sii_clean)))
		goto out;
	rh_secure_writer_plan_clone(&derived_writer, pre_writer);
	if (rh_ntfs_overlay_mount(&derived_overlay, &derived_writer, 0))
		goto out;
	derived_mounted = 1;
	if (rh_secure_stage_batch(&derived_overlay, pre_authority, before,
			&derived_after, &derived_plan) != RH_SECURE_STAGE_PLANNED ||
			derived_plan.operation_count != entry_count ||
			memcmp(derived_plan.pre_state_hash, pre_state, 32) ||
			memcmp(derived_plan.staged_state_hash, post_state, 32) ||
			!rh_secure_batch_cursor_equal(&derived_after, after))
		goto out;
	rh_secure_evidence_hash(post_authority, &post, staged_evidence);
	if (rh_secure_all_zero(staged_evidence, 32))
		goto out;
	for (i = 0; i < entry_count; i++) {
		const struct rh_write_operation *operation =
			&derived_writer.operations[derived_plan.initial_checkpoint + i];
		const struct rh_secure_recovery_entry *entry = &entries[i];
		unsigned char *actual = malloc(operation->length);
		unsigned char *expected_final = malloc(operation->length);
		int target_ok, hashes_ok, before_hash_ok, after_hash_ok;
		int read_ok = 0, bytes_ok = 0;

		target_ok = rh_secure_recovery_evidence_valid(entry, operation->kind,
			&operation->target, derived_plan.generation,
			derived_plan.pre_evidence_hash, staged_evidence);
		hashes_ok = rh_secure_recovery_hashes(entry, operation->before,
			operation->after);
		before_hash_ok = !memcmp(entry->target.semantic_before_hash,
			operation->target.semantic_before_hash, 32);
		after_hash_ok = !memcmp(entry->target.semantic_after_hash,
			operation->target.semantic_after_hash, 32);
		if (actual && expected_final) {
			read_ok = !rh_writer_read(post_writer, operation->offset,
				operation->length, actual) &&
				!rh_writer_read(&derived_writer, operation->offset,
					operation->length, expected_final);
			bytes_ok = read_ok && !memcmp(actual, expected_final,
				operation->length);
		}
		if (!actual || !expected_final ||
				entry->target_offset != operation->offset ||
				entry->length != operation->length ||
				!target_ok || !hashes_ok || !before_hash_ok || !after_hash_ok ||
				!bytes_ok) {
			free(actual);
			free(expected_final);
			goto out;
		}
		free(actual);
		free(expected_final);
	}
	result = 0;
out:
	if (derived_mounted)
		rh_ntfs_overlay_unmount(&derived_overlay);
	rh_writer_reset_plan(&derived_writer);
	rh_secure_inspection_destroy(&post);
	rh_secure_inspection_destroy(&pre);
	if (result && !errno)
		errno = EPERM;
	return result;
}
