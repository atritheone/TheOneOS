/*
 * Fail-closed, side-effect-free structural gate for T1OS native $LogFile
 * replay.  This translation unit deliberately has no ntfs-3g dependency so
 * the hostile-input boundary can be fuzzed with ASan/UBSan in isolation.
 */
#include "roothealth_replay_guard.h"

#include <limits.h>
#include <string.h>

#define RH_LOG_STANDARD 1U
#define RH_LOG_CHECKPOINT 2U
#define RH_LOG_MULTI_PAGE 1U
#define RH_ACTS_ON_MFT 2U
#define RH_LOG_RECORD_HEADER_SIZE 48U
#define RH_LOG_RECORD_FIXED_SIZE 80U
#define RH_RCRD_HEADER_SIZE 40U
#define RH_RCRD_USA_OFFSET 40U
#define RH_RCRD_USA_COUNT 9U
#define RH_RCRD_DATA_OFFSET 64U

#define UBIT(n) (UINT64_C(1) << (n))

static const struct rh_replay_action_policy action_policy[RH_REPLAY_ACTION_COUNT] = {
	{ "Noop", UBIT(0), RH_REPLAY_ACTION_CONTROL, NULL },
	{ "CompensationlogRecord", UBIT(0), RH_REPLAY_ACTION_CONTROL, NULL },
	{ "InitializeFileRecordSegment", UBIT(0), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "DeallocateFileRecordSegment", UBIT(2), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "WriteEndofFileRecordSegment", UBIT(4), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "CreateAttribute", UBIT(6), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "DeleteAttribute", UBIT(5), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "UpdateResidentValue", UBIT(7), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "UpdateNonResidentValue", UBIT(8), RH_REPLAY_ACTION_RAW_WRITE, NULL },
	{ "UpdateMappingPairs", UBIT(9), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "DeleteDirtyClusters", UBIT(0), RH_REPLAY_ACTION_CONTROL, NULL },
	{ "SetNewAttributeSizes", UBIT(11), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "AddIndexEntryRoot", UBIT(13), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "DeleteIndexEntryRoot", UBIT(12), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "AddIndexEntryAllocation", UBIT(15), RH_REPLAY_ACTION_INDX_WRITE, NULL },
	{ "DeleteIndexEntryAllocation", UBIT(14), RH_REPLAY_ACTION_INDX_WRITE, NULL },
	{ "WriteEndOfIndexBuffer", UBIT(16), RH_REPLAY_ACTION_INDX_WRITE, NULL },
	{ "SetIndexEntryVcnRoot", UBIT(17), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "SetIndexEntryVcnAllocation", UBIT(18), RH_REPLAY_ACTION_INDX_WRITE, NULL },
	{ "UpdateFileNameRoot", UBIT(19), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "UpdateFileNameAllocation", UBIT(20), RH_REPLAY_ACTION_INDX_WRITE, NULL },
	{ "SetBitsInNonResidentBitMap", UBIT(22), RH_REPLAY_ACTION_BITMAP_WRITE, NULL },
	{ "ClearBitsInNonResidentBitMap", UBIT(21), RH_REPLAY_ACTION_BITMAP_WRITE, NULL },
	{ "HotFix", UBIT(0), RH_REPLAY_ACTION_CONTROL, NULL },
	{ "EndTopLevelAction", UBIT(0), RH_REPLAY_ACTION_CONTROL, NULL },
	{ "PrepareTransaction", UBIT(0), RH_REPLAY_ACTION_CONTROL, NULL },
	{ "CommitTransaction", UBIT(0), RH_REPLAY_ACTION_CONTROL, NULL },
	{ "ForgetTransaction", UBIT(0), RH_REPLAY_ACTION_TRANSACTION_END, NULL },
	{ "OpenNonResidentAttribute", UBIT(0), RH_REPLAY_ACTION_CONTROL, NULL },
	{ "OpenAttributeTableDump", UBIT(0), RH_REPLAY_ACTION_CONTROL, NULL },
	{ "AttributeNamesDump", UBIT(0), RH_REPLAY_ACTION_CONTROL, NULL },
	{ "DirtyPageTableDump", UBIT(0), RH_REPLAY_ACTION_CONTROL, NULL },
	{ "TransactionTableDump", UBIT(0), RH_REPLAY_ACTION_CONTROL, NULL },
	{ "UpdateRecordDataRoot", UBIT(33), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "UpdateRecordDataAllocation", UBIT(34), RH_REPLAY_ACTION_INDX_WRITE, NULL },
	{ "UpdateRelativeDataInIndex", UBIT(35), RH_REPLAY_ACTION_MFT_WRITE, NULL },
	{ "UpdateRelativeDataInIndex2", UBIT(36), RH_REPLAY_ACTION_INDX_WRITE, NULL },
	{ "ZeroEndOfFileRecord", UBIT(0), RH_REPLAY_ACTION_MFT_WRITE, NULL }
};

static uint16_t rd16(const unsigned char *p)
{
	return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static uint32_t rd32(const unsigned char *p)
{
	return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
		((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t rd64(const unsigned char *p)
{
	return (uint64_t)rd32(p) | ((uint64_t)rd32(p + 4) << 32);
}

static int all_zero(const unsigned char *p, size_t length)
{
	while (length--)
		if (*p++)
			return 0;
	return 1;
}

static int all_ff(const unsigned char *p, size_t length)
{
	while (length--)
		if (*p++ != 0xffU)
			return 0;
	return 1;
}

static int add_ok(size_t left, size_t right, size_t limit, size_t *sum)
{
	if (left > limit || right > limit - left)
		return 0;
	*sum = left + right;
	return 1;
}

const struct rh_replay_action_policy *rh_replay_action_policy(unsigned int op)
{
	if (op >= RH_REPLAY_ACTION_COUNT)
		return NULL;
	return &action_policy[op];
}

int rh_replay_guard_profile(const struct rh_replay_geometry *geometry)
{
	uint32_t offset_bits;
	uint64_t address_units;

	if (!geometry || geometry->page_size != RH_REPLAY_PAGE_SIZE ||
		geometry->cluster_size != RH_REPLAY_PAGE_SIZE ||
		geometry->logfile_size < RH_REPLAY_MIN_LOGFILE_SIZE ||
		geometry->logfile_size > RH_REPLAY_MAX_LOGFILE_SIZE ||
		(geometry->logfile_size % RH_REPLAY_PAGE_SIZE) ||
		!geometry->volume_clusters ||
		geometry->volume_clusters > (UINT64_C(256) << 30) /
			RH_REPLAY_PAGE_SIZE ||
		geometry->mft_record_size != 1024U ||
		geometry->index_record_size != RH_REPLAY_PAGE_SIZE ||
		!geometry->sequence_bits || geometry->sequence_bits >= 64U ||
		geometry->client_sequence == UINT16_MAX || geometry->client_index)
		return -1;
	offset_bits = 64U - geometry->sequence_bits;
	address_units = geometry->logfile_size / 8U;
	if (offset_bits < 64U && address_units > (UINT64_C(1) << offset_bits))
		return -1;
	return 0;
}

int rh_replay_guard_unprotect_rcrd(unsigned char *page, size_t length,
		struct rh_replay_page_view *view)
{
	unsigned int sector;
	uint16_t usn;
	uint16_t next;
	uint16_t count;
	uint16_t position;

	if (!page || length != RH_REPLAY_PAGE_SIZE ||
		memcmp(page, "RCRD", 4) || rd16(page + 4) != RH_RCRD_USA_OFFSET ||
		rd16(page + 6) != RH_RCRD_USA_COUNT ||
		(rd32(page + 16) & ~1U) || !all_zero(page + 26, 6))
		return -1;
	next = rd16(page + 24);
	count = rd16(page + 20);
	position = rd16(page + 22);
	if (!count || count > RH_REPLAY_MAX_IO_PAGES || !position ||
		position > count || next > RH_REPLAY_PAGE_SIZE || (next & 7U) ||
		((rd32(page + 16) & 1U) ? next < RH_RCRD_DATA_OFFSET : next != 0U))
		return -1;
	usn = rd16(page + RH_RCRD_USA_OFFSET);
	if (!usn)
		return -1;
	for (sector = 1; sector < RH_RCRD_USA_COUNT; ++sector) {
		size_t tail = (size_t)sector * RH_REPLAY_SECTOR_SIZE - 2U;
		size_t replacement = RH_RCRD_USA_OFFSET + 2U * sector;

		if (rd16(page + tail) != usn)
			return -1;
		page[tail] = page[replacement];
		page[tail + 1] = page[replacement + 1];
	}
	if (view) {
		view->next_record_offset = next;
		view->page_count = count;
		view->page_position = position;
		view->flags = rd32(page + 16);
		view->file_offset = rd32(page + 60);
		view->copy_value = rd64(page + 8);
		view->last_end_lsn = rd64(page + 32);
	}
	return 0;
}

int rh_replay_guard_action(const unsigned char *record, size_t record_size,
		const struct rh_replay_geometry *geometry,
		uint64_t source_byte_offset, struct rh_replay_action_view *view)
{
	const struct rh_replay_action_policy *policy;
	enum rh_replay_action_class action_class;
	uint16_t redo = 0, undo = 0, redo_rel = 0, undo_rel = 0;
	uint16_t redo_length = 0, undo_length = 0, lcn_count = 0;
	uint16_t cluster_index = 0, record_offset = 0, attribute_offset = 0;
	uint16_t record_flags, attribute_flags = 0;
	uint32_t client_length, transaction_id, record_type;
	uint64_t this_lsn, previous_lsn, undo_next_lsn, mask;
	uint64_t target_vcn = 0, first_lcn = 0, target_cluster_bytes = 0;
	size_t fixed_end = 0, redo_at = 0, undo_at = 0;
	size_t redo_end = 0, undo_end = 0, payload_end = 0, extra_at = 0;
	size_t extra_length = 0, target_at = 0, target_object_size = 0;
	uint32_t offset_bits;
	unsigned int lcn_index;
	int windows_control_layout;

	if (!record || rh_replay_guard_profile(geometry) ||
		record_size < 88U || record_size > RH_REPLAY_MAX_ACTION_SIZE ||
		(record_size & 7U))
		return -1;
	client_length = rd32(record + 24);
	record_type = rd32(record + 32);
	record_flags = rd16(record + 40);
	transaction_id = rd32(record + 36);
	if (client_length > RH_REPLAY_MAX_ACTION_SIZE - RH_LOG_RECORD_HEADER_SIZE ||
		(size_t)client_length + RH_LOG_RECORD_HEADER_SIZE != record_size ||
		rd16(record + 28) != geometry->client_sequence ||
		rd16(record + 30) != geometry->client_index ||
		rd16(record + 42) || rd16(record + 44) || rd16(record + 46))
		return -1;

	this_lsn = rd64(record);
	previous_lsn = rd64(record + 8);
	undo_next_lsn = rd64(record + 16);
	if (!this_lsn || (previous_lsn && previous_lsn >= this_lsn) ||
		(undo_next_lsn && undo_next_lsn >= this_lsn))
		return -1;
	if (source_byte_offset != RH_REPLAY_SOURCE_UNKNOWN) {
		int spans_pages;

		offset_bits = 64U - geometry->sequence_bits;
		mask = offset_bits == 64U ? UINT64_MAX : (UBIT(offset_bits) - 1U);
		if (source_byte_offset >= geometry->logfile_size ||
			(source_byte_offset & 7U) ||
			(this_lsn & mask) != source_byte_offset / 8U ||
			!(this_lsn & ~mask))
			return -1;
		spans_pages = record_size > RH_REPLAY_PAGE_SIZE -
			(source_byte_offset & (RH_REPLAY_PAGE_SIZE - 1U));
		if (!!(record_flags & RH_LOG_MULTI_PAGE) != !!spans_pages)
			return -1;
	}

	/* The client-restart record contains NTFS_RESTART, not LOG_REC_HDR. */
	if (record_type == RH_LOG_CHECKPOINT) {
		uint32_t major, minor;
		unsigned int i;
		int windows_extended;

		if (transaction_id || (record_flags & ~RH_LOG_MULTI_PAGE) ||
			undo_next_lsn ||
			(client_length != 0x68U && client_length != 0x70U) ||
			record_size < 112U)
			return -1;
		major = rd32(record + 48);
		minor = rd32(record + 52);
		windows_extended = major == 1U && minor == 0U &&
			client_length == 0x70U && record_size == 160U;
		if (!windows_extended && !(major == 1U && minor == 1U &&
			client_length == 0x68U && record_size == 152U))
			return -1;
		for (i = 0; i < 5U; ++i) {
			uint64_t referenced_lsn = rd64(record + 56U + 8U * i);
			if (referenced_lsn && (referenced_lsn > this_lsn ||
				(i && referenced_lsn == this_lsn)))
				return -1;
		}
		for (i = 0; i < 4U; ++i) {
			uint64_t referenced_lsn = rd64(record + 64U + 8U * i);
			uint32_t table_length = rd32(record + 96U + 4U * i);
			if (!!referenced_lsn != !!table_length ||
				table_length > RH_REPLAY_MAX_ACTION_SIZE)
				return -1;
		}
		if (windows_extended) {
			uint64_t extension_lsns[2];

			extension_lsns[0] = rd64(record + 120U);
			extension_lsns[1] = rd64(record + 152U);
			if (rd64(record + 128U) != geometry->page_size ||
				rd64(record + 112U) || rd64(record + 136U) ||
				rd64(record + 144U))
				return -1;
			offset_bits = 64U - geometry->sequence_bits;
			mask = offset_bits == 64U ? UINT64_MAX :
				(UBIT(offset_bits) - 1U);
			for (i = 0; i < 2U; ++i)
				if (!extension_lsns[i] || !(extension_lsns[i] & ~mask) ||
					(extension_lsns[i] & mask) >=
						geometry->logfile_size / 8U)
					return -1;
		} else if (!all_zero(record + 112U, record_size - 112U)) {
			return -1;
		}
		action_class = RH_REPLAY_ACTION_CHECKPOINT;
		goto fill_view;
	}
	if (record_type != RH_LOG_STANDARD || !transaction_id)
		return -1;

	redo = rd16(record + 48);
	undo = rd16(record + 50);
	if (redo >= RH_REPLAY_ACTION_COUNT || undo >= RH_REPLAY_ACTION_COUNT)
		return -1;
	policy = &action_policy[redo];
	if (!(policy->undo_mask & UBIT(undo)) ||
		policy->action_class == RH_REPLAY_ACTION_DENY)
		return -1;
	action_class = policy->action_class;
	redo_rel = rd16(record + 52);
	redo_length = rd16(record + 54);
	undo_rel = rd16(record + 56);
	undo_length = rd16(record + 58);
	lcn_count = rd16(record + 62);
	record_offset = rd16(record + 64);
	attribute_offset = rd16(record + 66);
	cluster_index = rd16(record + 68);
	attribute_flags = rd16(record + 70);
	windows_control_layout = redo >= 29U && redo <= 32U &&
		rd16(record + 60) == 24U && attribute_flags == RH_ACTS_ON_MFT;
	if ((redo_rel & 7U) || (undo_rel & 7U) ||
		!add_ok(RH_LOG_RECORD_FIXED_SIZE, (size_t)lcn_count * 8U,
			record_size, &fixed_end) ||
		(redo_length && redo_rel < 0x28U) ||
		(undo_length && undo_rel < 0x28U))
		return -1;
	redo_at = (lcn_count || windows_control_layout ? 0x30U : 0x28U) + redo_rel;
	undo_at = (lcn_count || windows_control_layout ? 0x30U : 0x28U) + undo_rel;
	if (!add_ok(redo_at, redo_length, record_size, &redo_end) ||
		!add_ok(undo_at, undo_length, record_size, &undo_end) ||
		(redo_length && redo_at < fixed_end) ||
		(undo_length && undo_at < fixed_end))
		return -1;
	if (redo_length && undo_length) {
		if (redo_at == undo_at) {
			if (redo_length != undo_length)
				return -1;
			payload_end = redo_end;
		} else if (redo_at == fixed_end &&
			undo_at == ((redo_end + 7U) & ~(size_t)7U)) {
			if (!all_zero(record + redo_end, undo_at - redo_end))
				return -1;
			payload_end = undo_end;
		} else if (undo_at == fixed_end &&
			redo_at == ((undo_end + 7U) & ~(size_t)7U)) {
			if (!all_zero(record + undo_end, redo_at - undo_end))
				return -1;
			payload_end = redo_end;
		} else {
			return -1;
		}
	} else if (redo_length) {
		if (redo_at != fixed_end + (windows_control_layout ? 8U : 0U) ||
			(windows_control_layout &&
			 !all_ff(record + fixed_end, 8U)))
			return -1;
		payload_end = redo_end;
	} else if (undo_length) {
		if (undo_at != fixed_end)
			return -1;
		payload_end = undo_end;
	} else {
		payload_end = fixed_end;
	}
	extra_at = (payload_end + 7U) & ~(size_t)7U;
	if (extra_at > record_size)
		return -1;
	if (windows_control_layout && redo == 30U) {
		if (extra_at - payload_end != 6U)
			return -1;
	} else if (!all_zero(record + payload_end, extra_at - payload_end)) {
		return -1;
	}
	extra_length = record_size - extra_at;

	/* These two operations only update the analysis dirty-page table. */
	if (action_class == RH_REPLAY_ACTION_CONTROL && redo == 10U) {
		size_t at;

		if ((record_flags & ~7U) || (record_flags & 6U) == 6U ||
			rd16(record + 60) || lcn_count ||
			cluster_index || record_offset || attribute_offset ||
			attribute_flags || rd64(record + 72) || undo_length ||
			undo_rel || redo_length < 16U || (redo_length & 15U) ||
			extra_length)
			return -1;
		for (at = redo_at; at < redo_end; at += 16U) {
			uint64_t lcn = rd64(record + at);
			uint64_t count = rd64(record + at + 8U);

			if (!count || lcn >= geometry->volume_clusters ||
				count > geometry->volume_clusters - lcn)
				return -1;
		}
		goto fill_view;
	}
	if (action_class == RH_REPLAY_ACTION_CONTROL && redo == 23U) {
		if ((record_flags & ~7U) || (record_flags & 6U) == 6U ||
			!rd16(record + 60) || lcn_count != 1U ||
			cluster_index || record_offset || attribute_offset ||
			attribute_flags || redo_length || undo_length || redo_rel ||
			undo_rel || extra_length)
			return -1;
		target_vcn = rd64(record + 72);
		first_lcn = rd64(record + 80);
		if (target_vcn > INT64_MAX || first_lcn > INT64_MAX ||
			first_lcn >= geometry->volume_clusters)
			return -1;
		goto fill_view;
	}

	if (action_class == RH_REPLAY_ACTION_CONTROL ||
		action_class == RH_REPLAY_ACTION_TRANSACTION_END) {
		if ((record_flags & ~7U) || (record_flags & 6U) == 6U ||
			lcn_count || cluster_index ||
			record_offset || attribute_offset ||
			rd64(record + 72))
			return -1;
		if (redo == 28U) {
			/* target_attribute is the restart-table byte offset. */
			if (!rd16(record + 60))
				return -1;
		} else if (redo >= 29U && redo <= 32U) {
			if (rd16(record + 60) && rd16(record + 60) != 24U)
				return -1;
		} else if (rd16(record + 60)) {
			return -1;
		}
		switch (redo) {
		case 0U:
		case 1U:
		case 24U:
		case 25U:
		case 26U:
		case 27U:
			if (attribute_flags || redo_length || undo_length ||
				redo_rel || undo_rel ||
				record_size != 88U ||
				!all_zero(record + RH_LOG_RECORD_FIXED_SIZE,
					record_size - RH_LOG_RECORD_FIXED_SIZE))
				return -1;
			break;
		case 28U:
			if (attribute_flags ||
				(redo_length != 40U && redo_length != 44U) ||
				(undo_length & 1U) || undo_length > 510U || extra_length)
				return -1;
			break;
		case 29U:
		case 31U:
		case 32U:
			if ((attribute_flags && attribute_flags != RH_ACTS_ON_MFT) ||
				redo_length < 24U || undo_length ||
				(extra_length && (extra_length != 8U ||
				 !all_zero(record + extra_at, extra_length))))
				return -1;
			break;
		case 30U:
			if (redo_length) {
				if (attribute_flags != RH_ACTS_ON_MFT || undo_length ||
					!windows_control_layout || extra_length)
					return -1;
				extra_at = redo_at;
				extra_length = redo_length;
			} else if (attribute_flags || undo_length || redo_rel ||
				undo_rel || !extra_length) {
				return -1;
			}
			break;
		default:
			return -1;
		}
		goto fill_view;
	}

	target_vcn = rd64(record + 72);
	if (!lcn_count || lcn_count != 1U || target_vcn > INT64_MAX ||
		(record_flags & ~7U) || (record_flags & 6U) == 6U)
		return -1;
	first_lcn = rd64(record + 80);
	for (lcn_index = 0; lcn_index < lcn_count; ++lcn_index) {
		uint64_t lcn = rd64(record + 80U + 8U * lcn_index);
		if (lcn > INT64_MAX || lcn >= geometry->volume_clusters)
			return -1;
	}
	target_cluster_bytes = (uint64_t)lcn_count * geometry->cluster_size;
	if (action_class == RH_REPLAY_ACTION_RAW_WRITE && attribute_flags == 8U)
		action_class = RH_REPLAY_ACTION_INDX_WRITE;
	switch (action_class) {
	case RH_REPLAY_ACTION_MFT_WRITE:
		if (attribute_flags != RH_ACTS_ON_MFT)
			return -1;
		target_at = (size_t)cluster_index * RH_REPLAY_SECTOR_SIZE;
		target_object_size = geometry->mft_record_size;
		if (target_at % target_object_size)
			return -1;
		break;
	case RH_REPLAY_ACTION_INDX_WRITE:
		if (attribute_flags != 8U || cluster_index)
			return -1;
		target_object_size = geometry->index_record_size;
		break;
	case RH_REPLAY_ACTION_RAW_WRITE:
		if (attribute_flags || cluster_index)
			return -1;
		target_object_size = (size_t)target_cluster_bytes;
		break;
	case RH_REPLAY_ACTION_BITMAP_WRITE:
		if (attribute_flags || cluster_index || record_offset ||
			attribute_offset || redo_length != 8U || undo_length != 8U ||
			!((redo == 21U && undo == 22U) ||
			  (redo == 22U && undo == 21U)) ||
			memcmp(record + redo_at, record + undo_at, 8))
			return -1;
		if (!rd32(record + redo_at + 4) ||
			rd32(record + redo_at) >= target_cluster_bytes * 8U ||
			rd32(record + redo_at + 4) > target_cluster_bytes * 8U -
				rd32(record + redo_at))
			return -1;
		target_object_size = (size_t)target_cluster_bytes;
		break;
	default:
		return -1;
	}
	if ((uint64_t)target_at + target_object_size > target_cluster_bytes ||
		(size_t)record_offset + attribute_offset > target_object_size ||
		redo_length > target_object_size -
			((size_t)record_offset + attribute_offset) ||
		undo_length > target_object_size -
			((size_t)record_offset + attribute_offset) ||
		extra_length)
		return -1;

	/* Tight qualified subset of the kernel operation grammar. */
	switch (redo) {
	case 2U:
		if (!redo_length || undo || undo_length)
			return -1;
		break;
	case 3U: {
		uint64_t record_number = target_vcn *
			(geometry->cluster_size / geometry->mft_record_size) +
			target_at / geometry->mft_record_size;

		/*
		 * NTFS logs the exact 24-byte FILE header before-image as an
		 * InitializeFileRecordSegment undo.  The redo has no payload and
		 * clears IN_USE while incrementing the sequence number.  Never
		 * permit this operation for the fixed metadata/reserved records.
		 */
		if (record_number < 24U || record_offset || attribute_offset ||
			redo_length || undo_length != 24U)
			return -1;
		break;
	}
	case 4U:
		/* Variable-size tails reach legacy resize helpers with open TODOs. */
		if (redo_length < 8U || redo_length != undo_length)
			return -1;
		break;
	case 5U:
	case 12U:
	case 14U:
		if (!redo_length || undo_length || undo == 1U)
			return -1;
		break;
	case 6U:
	case 13U:
	case 15U:
		if (redo_length || !undo_length || undo == 1U)
			return -1;
		break;
	case 11U:
		if (redo_length != undo_length ||
			(redo_length != 24U && redo_length != 32U))
			return -1;
		break;
	case 17U:
	case 18U:
		if (redo_length != 8U || undo_length != 8U)
			return -1;
		break;
	case 19U:
	case 20U:
		if (!redo_length || redo_length != undo_length || redo_length > 64U)
			return -1;
		break;
	case 21U:
	case 22U:
		break;
	case 35U:
	case 36U:
		if ((redo_length != 4U && redo_length != 8U) ||
			undo_length != redo_length)
			return -1;
		if (redo_length == 4U) {
			if ((uint32_t)(rd32(record + redo_at) +
					rd32(record + undo_at)) != 0U)
				return -1;
		} else if (rd64(record + redo_at) +
				rd64(record + undo_at) != 0U) {
			return -1;
		}
		break;
	case 37U:
		if (!redo_length || undo_length || undo ||
			(size_t)record_offset + attribute_offset + redo_length !=
				target_object_size ||
			!all_zero(record + redo_at, redo_length))
			return -1;
		break;
	default:
		if (!redo_length || redo_length != undo_length || undo == 1U)
			return -1;
		break;
	}

fill_view:
	if (view) {
		memset(view, 0, sizeof(*view));
		view->record_type = record_type;
		view->redo_operation = redo;
		view->undo_operation = undo;
		view->lcn_count = lcn_count;
		view->cluster_index = cluster_index;
		view->record_offset = record_offset;
		view->attribute_offset = attribute_offset;
		view->redo_length = redo_length;
		view->undo_length = undo_length;
		view->record_flags = record_flags;
		view->transaction_id = transaction_id;
		view->this_lsn = this_lsn;
		view->previous_lsn = previous_lsn;
		view->undo_next_lsn = undo_next_lsn;
		view->target_vcn = target_vcn;
		view->first_lcn = first_lcn;
		view->record_size = record_size;
		view->redo_data_offset = redo_at;
		view->undo_data_offset = undo_at;
		view->extra_data_offset = extra_at;
		view->extra_data_length = extra_length;
		view->target_slice_offset = target_at;
		view->target_object_size = target_object_size;
		view->action_class = action_class;
	}
	return 0;
}
