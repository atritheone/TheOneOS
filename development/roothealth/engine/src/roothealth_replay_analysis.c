/*
 * Bounded ARIES-style analysis for the T1OS native NTFS replay profile.
 * This file has no ntfs-3g dependency and never performs I/O.
 */
#include "roothealth_replay_analysis.h"
#include "roothealth_replay_analysis_internal.h"

#include <stdlib.h>
#include <string.h>

#define RH_RESTART_TABLE_HEADER 24U
#define RH_TRANSACTION_ENTRY_SIZE 40U
#define RH_OPEN_ATTRIBUTE_ENTRY_SIZE 40U
#define RH_DIRTY_PAGE_ENTRY_SIZE 40U
#define RH_ENTRY_ALLOCATED UINT32_C(0xffffffff)

enum rh_tx_state {
	RH_TX_NONE = 0,
	RH_TX_ACTIVE = 1,
	RH_TX_PREPARED = 2,
	RH_TX_COMMITTED = 3,
	RH_TX_FORGOTTEN = 4
};

struct rh_tx {
	uint32_t id;
	uint64_t first_lsn;
	uint64_t last_lsn;
	uint64_t undo_lsn;
	enum rh_tx_state state;
	int present;
};

struct rh_dirty_page {
	uint32_t target_attribute;
	uint64_t vcn;
	uint64_t oldest_lsn;
	uint64_t lcn;
	int lcn_valid;
	int present;
};

struct rh_checkpoint {
	uint64_t analysis_start_lsn;
	uint64_t table_lsn[4];
	uint32_t table_length[4];
	uint64_t this_lsn;
	int present;
};

struct rh_table_view {
	const unsigned char *bytes;
	size_t length;
	uint16_t entry_size;
	uint16_t slots;
	uint16_t allocated;
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

static int valid_file_reference(uint64_t reference)
{
	return (uint16_t)(reference >> 48) != 0;
}

static int restart_offset(uint32_t offset, uint16_t entry_size,
		uint16_t slots)
{
	uint32_t end = RH_RESTART_TABLE_HEADER + (uint32_t)entry_size * slots;

	return offset >= RH_RESTART_TABLE_HEADER && offset < end &&
		!((offset - RH_RESTART_TABLE_HEADER) % entry_size);
}

static int validate_restart_table(const unsigned char *bytes, size_t length,
		uint16_t exact_entry_size, struct rh_table_view *view)
{
	unsigned char *visited = NULL;
	uint16_t entry_size, slots, allocated, i;
	uint32_t table_end, first_free, last_free, cursor;
	unsigned int allocated_seen = 0, free_seen = 0;
	int ok = 0;

	if (!bytes || length < RH_RESTART_TABLE_HEADER)
		return -1;
	entry_size = rd16(bytes);
	slots = rd16(bytes + 2);
	allocated = rd16(bytes + 4);
	if (entry_size != exact_entry_size || !slots || allocated > slots ||
		!all_zero(bytes + 6, 6) ||
		(uint32_t)entry_size * slots > length - RH_RESTART_TABLE_HEADER)
		return -1;
	table_end = RH_RESTART_TABLE_HEADER + (uint32_t)entry_size * slots;
	if (table_end != length)
		return -1;
	first_free = rd32(bytes + 16);
	last_free = rd32(bytes + 20);
	if (!!first_free != !!last_free ||
		(first_free && (!restart_offset(first_free, entry_size, slots) ||
		 !restart_offset(last_free, entry_size, slots))))
		return -1;
	visited = calloc(slots, 1U);
	if (!visited)
		return -1;
	for (i = 0; i < slots; ++i) {
		uint32_t next = rd32(bytes + RH_RESTART_TABLE_HEADER +
			(size_t)i * entry_size);
		if (next == RH_ENTRY_ALLOCATED) {
			++allocated_seen;
		} else if (next && !restart_offset(next, entry_size, slots)) {
			goto out;
		}
	}
	if (allocated_seen != allocated)
		goto out;
	cursor = first_free;
	while (cursor) {
		unsigned int slot = (cursor - RH_RESTART_TABLE_HEADER) / entry_size;
		uint32_t next;

		if (slot >= slots || visited[slot])
			goto out;
		visited[slot] = 1;
		++free_seen;
		next = rd32(bytes + cursor);
		if (cursor == last_free && next)
			goto out;
		cursor = next;
	}
	if (free_seen != (unsigned int)slots - allocated)
		goto out;
	if (view) {
		view->bytes = bytes;
		view->length = length;
		view->entry_size = entry_size;
		view->slots = slots;
		view->allocated = allocated;
	}
	ok = 1;
out:
	free(visited);
	return ok ? 0 : -1;
}

static struct rh_tx *find_tx(struct rh_tx *transactions, size_t count,
		uint32_t id, int create)
{
	size_t i;

	for (i = 0; i < count; ++i)
		if (transactions[i].present && transactions[i].id == id)
			return &transactions[i];
	if (!create)
		return NULL;
	for (i = 0; i < count; ++i)
		if (!transactions[i].present) {
			memset(&transactions[i], 0, sizeof(transactions[i]));
			transactions[i].present = 1;
			transactions[i].id = id;
			transactions[i].state = RH_TX_ACTIVE;
			return &transactions[i];
		}
	return NULL;
}

static int parse_transaction_table(const unsigned char *bytes, size_t length,
		struct rh_tx *transactions, size_t transaction_count,
		uint64_t table_lsn)
{
	struct rh_table_view table;
	uint16_t i;

	if (validate_restart_table(bytes, length, RH_TRANSACTION_ENTRY_SIZE,
			&table))
		return -1;
	for (i = 0; i < table.slots; ++i) {
		const unsigned char *entry = bytes + RH_RESTART_TABLE_HEADER +
			(size_t)i * table.entry_size;
		struct rh_tx *tx;
		uint8_t state;
		uint64_t first_lsn, previous_lsn, undo_lsn;

		if (rd32(entry) != RH_ENTRY_ALLOCATED)
			continue;
		state = entry[4];
		first_lsn = rd64(entry + 8);
		previous_lsn = rd64(entry + 16);
		undo_lsn = rd64(entry + 24);
		if (state < RH_TX_ACTIVE || state > RH_TX_COMMITTED ||
			!all_zero(entry + 5, 3) || !first_lsn ||
			first_lsn > previous_lsn || previous_lsn >= table_lsn ||
			(undo_lsn && (undo_lsn < first_lsn || undo_lsn > previous_lsn)) ||
			rd32(entry + 32) > RH_REPLAY_MAX_ACTIONS ||
			rd32(entry + 36) > RH_REPLAY_MAX_LOGFILE_SIZE)
			return -1;
		tx = find_tx(transactions, transaction_count,
			RH_RESTART_TABLE_HEADER + (uint32_t)i * table.entry_size, 1);
		if (!tx)
			return -1;
		tx->first_lsn = first_lsn;
		tx->last_lsn = previous_lsn;
		tx->undo_lsn = undo_lsn;
		tx->state = (enum rh_tx_state)state;
	}
	return 0;
}

static int parse_open_attribute_table(const unsigned char *bytes, size_t length,
		struct rh_open_attribute *attributes, size_t attribute_count,
		uint64_t table_lsn, uint16_t *open_entry_size)
{
	struct rh_table_view table;
	uint16_t entry_size;
	uint16_t i;

	if (!bytes || length < RH_RESTART_TABLE_HEADER)
		return -1;
	entry_size = rd16(bytes);
	if ((entry_size != RH_OPEN_ATTRIBUTE_ENTRY_SIZE && entry_size != 44U) ||
		validate_restart_table(bytes, length, entry_size, &table))
		return -1;
	if (table.slots > attribute_count)
		return -1;
	for (i = 0; i < table.slots; ++i) {
		const unsigned char *entry = bytes + RH_RESTART_TABLE_HEADER +
			(size_t)i * table.entry_size;
		uint32_t type, bytes_per_index;
		uint64_t reference, open_lsn;
		uint16_t name_bytes;
		int expects_name;

		if (rd32(entry) != RH_ENTRY_ALLOCATED)
			continue;
		if (entry_size == RH_OPEN_ATTRIBUTE_ENTRY_SIZE) {
			bytes_per_index = rd32(entry + 4);
			type = rd32(entry + 8);
			reference = rd64(entry + 16);
			open_lsn = rd64(entry + 24);
			expects_name = entry[13];
			name_bytes = (uint16_t)entry[14] * 2U;
			if (entry[12] > 1U || entry[13] > 1U || entry[15])
				return -1;
		} else {
			reference = rd64(entry + 8);
			open_lsn = rd64(entry + 16);
			type = rd32(entry + 28);
			bytes_per_index = rd32(entry + 40);
			expects_name = entry[25];
			name_bytes = (uint16_t)entry[32] * 2U;
			if (entry[24] > 1U || entry[25] > 1U || entry[26] || entry[27] ||
				entry[33] || entry[34] || entry[35])
				return -1;
		}
		if (!type || (type & 0xfU) || type > 0x100U ||
			((type == 0xa0U) != (bytes_per_index == 4096U)) ||
			!!expects_name != !!name_bytes ||
			!valid_file_reference(reference) ||
			(open_lsn && open_lsn >= table_lsn))
			return -1;
		attributes[i].present = 1;
		attributes[i].key = RH_RESTART_TABLE_HEADER +
			(uint32_t)i * table.entry_size;
		attributes[i].type = type;
		attributes[i].file_reference = reference;
		attributes[i].bytes_per_index = bytes_per_index;
		attributes[i].open_lsn = open_lsn;
		attributes[i].source_lsn = table_lsn;
		attributes[i].name_bytes = name_bytes;
		attributes[i].source_kind = 1U;
		attributes[i].expects_name = (uint8_t)expects_name;
	}
	if (open_entry_size)
		*open_entry_size = entry_size;
	return 0;
}

static int parse_dirty_page_table(const unsigned char *bytes, size_t length,
		struct rh_dirty_page *pages, size_t page_count,
		const struct rh_open_attribute *attributes, size_t attribute_count,
		uint16_t open_entry_size,
		const struct rh_replay_geometry *geometry, uint64_t table_lsn)
{
	struct rh_table_view table;
	uint16_t i;

	if (!open_entry_size ||
		validate_restart_table(bytes, length, RH_DIRTY_PAGE_ENTRY_SIZE,
			&table) || table.slots > page_count)
		return -1;
	for (i = 0; i < table.slots; ++i) {
		const unsigned char *entry = bytes + RH_RESTART_TABLE_HEADER +
			(size_t)i * table.entry_size;
		uint32_t key, attribute_slot;
		uint64_t oldest_lsn, lcn;
		uint16_t j;

		if (rd32(entry) != RH_ENTRY_ALLOCATED)
			continue;
		key = rd32(entry + 4);
		if (!restart_offset(key, open_entry_size,
				(uint16_t)attribute_count))
			return -1;
		attribute_slot = (key - RH_RESTART_TABLE_HEADER) / open_entry_size;
		oldest_lsn = rd64(entry + 24);
		lcn = rd64(entry + 32);
		if (!attributes[attribute_slot].present || rd32(entry + 8) != 4096U ||
			rd32(entry + 12) != 1U || !oldest_lsn ||
			oldest_lsn >= table_lsn || lcn >= geometry->volume_clusters)
			return -1;
		for (j = 0; j < i; ++j)
			if (pages[j].present && pages[j].target_attribute == key &&
				pages[j].vcn == rd64(entry + 16))
				return -1;
		pages[i].present = 1;
		pages[i].target_attribute = key;
		pages[i].vcn = rd64(entry + 16);
		pages[i].oldest_lsn = oldest_lsn;
		pages[i].lcn = lcn;
		pages[i].lcn_valid = 1;
	}
	return 0;
}

static struct rh_dirty_page *find_dirty_page(struct rh_dirty_page *pages,
		size_t count, uint32_t target_attribute, uint64_t vcn)
{
	size_t i;

	for (i = 0; i < count; ++i)
		if (pages[i].present &&
			pages[i].target_attribute == target_attribute &&
			pages[i].vcn == vcn)
			return &pages[i];
	return NULL;
}

static int apply_delete_dirty_clusters(
		const struct rh_replay_analysis_record *record,
		const struct rh_replay_action_view *view,
		struct rh_dirty_page *pages, size_t page_count)
{
	size_t at, i;
	const unsigned char *payload;

	if (!record || !view || view->redo_operation != 10U ||
		!view->redo_length || (view->redo_length & 15U))
		return -1;
	payload = record->bytes + view->redo_data_offset;
	for (at = 0; at < view->redo_length; at += 16U) {
		uint64_t first = rd64(payload + at);
		uint64_t count = rd64(payload + at + 8U);

		if (!count || first > UINT64_MAX - count)
			return -1;
		for (i = 0; i < page_count; ++i)
			if (pages[i].present && pages[i].lcn_valid &&
				pages[i].lcn >= first && pages[i].lcn - first < count) {
				pages[i].lcn = 0;
				pages[i].lcn_valid = 0;
			}
	}
	return 0;
}

static int apply_hotfix(const struct rh_replay_analysis_record *record,
		const struct rh_replay_action_view *view,
		struct rh_dirty_page *pages, size_t page_count,
		const struct rh_open_attribute *attributes, size_t attribute_count,
		uint16_t open_entry_size)
{
	struct rh_dirty_page *page;
	uint32_t key, slot;

	if (!record || !view || view->redo_operation != 23U ||
		!open_entry_size)
		return -1;
	key = rd16(record->bytes + 60);
	if (!restart_offset(key, open_entry_size, (uint16_t)attribute_count))
		return -1;
	slot = (key - RH_RESTART_TABLE_HEADER) / open_entry_size;
	if (!attributes[slot].present)
		return -1;
	page = find_dirty_page(pages, page_count, key, view->target_vcn);
	if (!page)
		return -1;
	page->lcn = view->first_lcn;
	page->lcn_valid = 1;
	return 0;
}

static int parse_attribute_names(const unsigned char *bytes, size_t length,
		struct rh_open_attribute *attributes, size_t attribute_count,
		uint16_t open_entry_size)
{
	size_t offset = 0;
	int terminated = 0;

	if (!open_entry_size)
		return -1;
	while (offset + 4U <= length) {
		uint16_t key = rd16(bytes + offset);
		uint16_t name_bytes = rd16(bytes + offset + 2U);
		uint32_t slot;

		if (!key) {
			terminated = 1;
			offset += 4U;
			break;
		}
		if (!name_bytes || (name_bytes & 1U) || name_bytes > 510U ||
			name_bytes > length - offset - 4U ||
			!restart_offset(key, open_entry_size,
				(uint16_t)attribute_count))
			return -1;
		slot = (key - RH_RESTART_TABLE_HEADER) / open_entry_size;
		if (!attributes[slot].present || attributes[slot].name_present ||
			(attributes[slot].expects_name &&
			 attributes[slot].name_bytes != name_bytes) ||
			(!attributes[slot].expects_name && attributes[slot].name_bytes))
			return -1;
		attributes[slot].expects_name = 1;
		attributes[slot].name_bytes = name_bytes;
		attributes[slot].name_present = 1;
		memcpy(attributes[slot].name_utf16le, bytes + offset + 4U,
			name_bytes);
		offset += 4U + name_bytes;
	}
	return terminated && all_zero(bytes + offset, length - offset) ? 0 : -1;
}

static int parse_dynamic_open_attribute(
		const struct rh_replay_analysis_record *record,
		const struct rh_replay_action_view *view,
		struct rh_open_attribute *attributes, size_t attribute_count,
		uint16_t *open_entry_size)
{
	const unsigned char *entry;
	uint32_t key, slot, type, bytes_per_index;
	uint64_t reference, open_lsn;
	uint16_t name_bytes;
	int expects_name;

	if (!record || !view || view->redo_operation != 28U ||
		(view->redo_length != RH_OPEN_ATTRIBUTE_ENTRY_SIZE &&
		 view->redo_length != 44U))
		return -1;
	if (!open_entry_size ||
		(*open_entry_size && *open_entry_size != view->redo_length))
		return -1;
	if (!*open_entry_size)
		*open_entry_size = view->redo_length;
	key = rd16(record->bytes + 60);
	if (!restart_offset(key, *open_entry_size,
			(uint16_t)attribute_count))
		return -1;
	slot = (key - RH_RESTART_TABLE_HEADER) / *open_entry_size;
	entry = record->bytes + view->redo_data_offset;
	if (view->redo_length == RH_OPEN_ATTRIBUTE_ENTRY_SIZE) {
		bytes_per_index = rd32(entry + 4);
		type = rd32(entry + 8);
		reference = rd64(entry + 16);
		open_lsn = rd64(entry + 24);
		expects_name = entry[13];
		name_bytes = (uint16_t)entry[14] * 2U;
		if (entry[12] > 1U || entry[13] > 1U || entry[15])
			return -1;
	} else {
		reference = rd64(entry + 8);
		open_lsn = rd64(entry + 16);
		type = rd32(entry + 28);
		bytes_per_index = rd32(entry + 40);
		expects_name = entry[25];
		name_bytes = (uint16_t)entry[32] * 2U;
		if (entry[24] > 1U || entry[25] > 1U || entry[26] || entry[27] ||
			entry[33] || entry[34] || entry[35])
			return -1;
	}
	if (rd32(entry) != RH_ENTRY_ALLOCATED || !type || (type & 0xfU) ||
		type > 0x100U ||
		((type == 0xa0U) != (bytes_per_index == 4096U)) ||
		!!expects_name != !!view->undo_length ||
		name_bytes != view->undo_length ||
		!valid_file_reference(reference) ||
		(open_lsn && open_lsn > view->this_lsn) ||
		attributes[slot].present)
		return -1;
	attributes[slot].present = 1;
	attributes[slot].key = key;
	attributes[slot].type = type;
	attributes[slot].file_reference = reference;
	attributes[slot].bytes_per_index = bytes_per_index;
	attributes[slot].open_lsn = open_lsn;
	attributes[slot].source_lsn = view->this_lsn;
	attributes[slot].name_bytes = name_bytes;
	attributes[slot].source_kind = 2U;
	attributes[slot].expects_name = (uint8_t)expects_name;
	attributes[slot].name_present = (uint8_t)expects_name;
	if (name_bytes)
		memcpy(attributes[slot].name_utf16le,
			record->bytes + view->undo_data_offset, name_bytes);
	return 0;
}

static struct rh_replay_analysis_record *find_record_by_lsn(
		struct rh_replay_analysis_record *records, size_t count, uint64_t lsn)
{
	size_t i;

	for (i = 0; i < count; ++i)
		if (rd64(records[i].bytes) == lsn)
			return &records[i];
	return NULL;
}

static int operation_is_mutation(enum rh_replay_action_class action_class)
{
	return action_class == RH_REPLAY_ACTION_MFT_WRITE ||
		action_class == RH_REPLAY_ACTION_INDX_WRITE ||
		action_class == RH_REPLAY_ACTION_RAW_WRITE ||
		action_class == RH_REPLAY_ACTION_BITMAP_WRITE;
}

int rh_replay_analysis_plan_export(struct rh_replay_analysis_record *records,
		size_t record_count, const struct rh_replay_geometry *geometry,
		uint64_t synced_lsn, uint64_t committed_lsn,
		rh_replay_analysis_complete_consumer consumer, void *consumer_opaque,
		struct rh_replay_analysis_result *result)
{
	struct rh_replay_action_view *views = NULL;
	struct rh_tx *transactions = NULL;
	struct rh_open_attribute *attributes = NULL;
	struct rh_dirty_page *dirty_pages = NULL;
	struct rh_checkpoint checkpoint;
	uint64_t observed_table_lsn[4] = { 0, 0, 0, 0 };
	uint32_t observed_table_length[4] = { 0, 0, 0, 0 };
	struct rh_replay_analysis_result local_result;
	size_t capacity, i;
	uint16_t open_entry_size = 0;
	uint64_t prior_lsn = 0, analysis_start = 0;
	uint64_t previous_checkpoint_lsn = 0;
	int rc = -1;

	if (!records || !record_count || record_count > RH_REPLAY_MAX_ACTIONS ||
		rh_replay_guard_profile(geometry))
		return -1;
	capacity = record_count + 64U;
	views = calloc(record_count, sizeof(*views));
	transactions = calloc(capacity, sizeof(*transactions));
	attributes = calloc(capacity, sizeof(*attributes));
	dirty_pages = calloc(capacity, sizeof(*dirty_pages));
	if (!views || !transactions || !attributes || !dirty_pages)
		goto out;
	memset(&checkpoint, 0, sizeof(checkpoint));
	memset(&local_result, 0, sizeof(local_result));
	for (i = 0; i < record_count; ++i) {
		uint64_t lsn;

		records[i].plan_flags = 0;
		records[i].effective_lcn = 0;
		records[i].has_effective_lcn = 0;
		if (rh_replay_guard_action(records[i].bytes, records[i].size,
				geometry, RH_REPLAY_SOURCE_UNKNOWN, &views[i]))
			goto out;
		lsn = views[i].this_lsn;
		if ((prior_lsn && lsn <= prior_lsn) || lsn < synced_lsn ||
			lsn > committed_lsn)
			goto out;
		prior_lsn = lsn;
		if (views[i].action_class == RH_REPLAY_ACTION_CHECKPOINT) {
			unsigned int j;
			if (checkpoint.present)
				previous_checkpoint_lsn = checkpoint.this_lsn;
			memset(&checkpoint, 0, sizeof(checkpoint));
			checkpoint.present = 1;
			checkpoint.this_lsn = lsn;
			checkpoint.analysis_start_lsn = rd64(records[i].bytes + 56);
			for (j = 0; j < 4U; ++j) {
				checkpoint.table_lsn[j] = rd64(records[i].bytes + 64U + 8U * j);
				checkpoint.table_length[j] = rd32(records[i].bytes + 96U + 4U * j);
			}
			++local_result.checkpoint_records;
		}
	}

	/* Resolve and validate all four checkpoint analysis controls first. */
	if (checkpoint.present) {
		unsigned int table_index;
		static const uint16_t expected_op[4] = { 29U, 30U, 31U, 32U };

		analysis_start = checkpoint.analysis_start_lsn ?
			checkpoint.analysis_start_lsn : checkpoint.this_lsn;
		if (analysis_start > checkpoint.this_lsn || analysis_start < synced_lsn ||
			(previous_checkpoint_lsn &&
			 previous_checkpoint_lsn > analysis_start))
			goto out;
		for (table_index = 0; table_index < 4U; ++table_index) {
			struct rh_replay_analysis_record *control;
			struct rh_replay_action_view control_view;
			const unsigned char *payload;
			size_t payload_length;

			if (!checkpoint.table_lsn[table_index])
				continue;
			if (checkpoint.table_lsn[table_index] < synced_lsn ||
				checkpoint.table_lsn[table_index] >= checkpoint.this_lsn)
				goto out;
			control = find_record_by_lsn(records, record_count,
				checkpoint.table_lsn[table_index]);
			if (!control || rh_replay_guard_action(control->bytes, control->size,
					geometry, RH_REPLAY_SOURCE_UNKNOWN, &control_view) ||
				control_view.redo_operation != expected_op[table_index])
				goto out;
			payload = control->bytes + (table_index == 1U ?
				control_view.extra_data_offset : control_view.redo_data_offset);
			payload_length = table_index == 1U ? control_view.extra_data_length :
				control_view.redo_length;
			if (payload_length != checkpoint.table_length[table_index])
				goto out;
			observed_table_lsn[table_index] = control_view.this_lsn;
			observed_table_length[table_index] = (uint32_t)payload_length;
			switch (table_index) {
			case 0U:
				if (parse_open_attribute_table(payload, payload_length,
						attributes, capacity, control_view.this_lsn,
						&open_entry_size))
					goto out;
				++local_result.open_attribute_tables;
				break;
			case 1U:
				if (parse_attribute_names(payload, payload_length,
						attributes, capacity, open_entry_size))
					goto out;
				++local_result.attribute_name_tables;
				break;
			case 2U:
				if (parse_dirty_page_table(payload, payload_length,
						dirty_pages, capacity, attributes, capacity,
						open_entry_size, geometry, control_view.this_lsn))
					goto out;
				++local_result.dirty_page_tables;
				break;
			case 3U:
				if (parse_transaction_table(payload, payload_length,
						transactions, capacity, control_view.this_lsn))
					goto out;
				++local_result.transaction_tables;
				break;
			}
		}
		for (i = 0; i < capacity; ++i)
			if (attributes[i].present &&
				attributes[i].expects_name != attributes[i].name_present)
				goto out;
	} else {
		analysis_start = synced_lsn;
	}

	for (i = 0; i < record_count; ++i) {
		struct rh_replay_action_view *view = &views[i];
		struct rh_tx *tx;
		uint16_t op;
		int checkpoint_seeded_record;
		int redo_candidate = 1;

		if (view->action_class == RH_REPLAY_ACTION_CHECKPOINT ||
			view->this_lsn < analysis_start)
			continue;
		op = view->redo_operation;
		checkpoint_seeded_record = checkpoint.present &&
			view->this_lsn < checkpoint.this_lsn;
		if (checkpoint.present && operation_is_mutation(view->action_class)) {
			uint32_t slot;
			struct rh_dirty_page *page;

			if (!open_entry_size ||
				!restart_offset(rd16(records[i].bytes + 60),
					open_entry_size, (uint16_t)capacity))
				goto out;
			slot = (rd16(records[i].bytes + 60) - RH_RESTART_TABLE_HEADER) /
				open_entry_size;
			if (!attributes[slot].present)
				goto out;
			page = find_dirty_page(dirty_pages, capacity,
				rd16(records[i].bytes + 60), view->target_vcn);
			if (!page && checkpoint_seeded_record) {
				redo_candidate = 0;
			} else if (!page) {
				size_t j;

				for (j = 0; j < capacity && dirty_pages[j].present; ++j) { }
				if (j == capacity)
					goto out;
				dirty_pages[j].present = 1;
				dirty_pages[j].target_attribute = rd16(records[i].bytes + 60);
				dirty_pages[j].vcn = view->target_vcn;
				dirty_pages[j].oldest_lsn = view->this_lsn;
				dirty_pages[j].lcn = view->first_lcn;
				dirty_pages[j].lcn_valid = 1;
			} else if (checkpoint_seeded_record) {
				if (!page->lcn_valid || page->oldest_lsn > view->this_lsn)
					redo_candidate = 0;
			} else {
				/* Analysis after the checkpoint refreshes the DPT mapping. */
				if (!page->lcn_valid)
					page->oldest_lsn = view->this_lsn;
				page->lcn = view->first_lcn;
				page->lcn_valid = 1;
			}
		}

		/* A table dump is meaningful only as the checkpoint's exact control. */
		if (op >= 29U && op <= 32U) {
			if (!checkpoint.present ||
				view->this_lsn != checkpoint.table_lsn[op - 29U])
				goto out;
			continue;
		}
		/*
		 * Records covered by the checkpoint tables are still redo candidates
		 * (dirty-page oldest_lsn may precede the checkpoint), but their
		 * transaction state must not be applied a second time.
		 */
		if (checkpoint_seeded_record) {
			if (operation_is_mutation(view->action_class)) {
				if (redo_candidate)
					records[i].plan_flags |= RH_REPLAY_PLAN_REDO;
				++local_result.mutation_records;
			}
			continue;
		}
		/* Windows transaction ids are byte offsets in the restart table. */
		if (checkpoint.present && !restart_offset(view->transaction_id,
				RH_TRANSACTION_ENTRY_SIZE, (uint16_t)capacity))
			goto out;
		tx = find_tx(transactions, capacity, view->transaction_id, 1);
		if (!tx || tx->state == RH_TX_FORGOTTEN ||
			(view->previous_lsn != tx->last_lsn))
			goto out;
		if (!tx->first_lsn)
			tx->first_lsn = view->this_lsn;
		tx->last_lsn = view->this_lsn;
		if (view->undo_operation == 1U)
			tx->undo_lsn = view->undo_next_lsn;
		else if (operation_is_mutation(view->action_class) ||
			op == 10U || op == 23U)
			tx->undo_lsn = view->this_lsn;
		switch (op) {
		case 1U:
			/* A CLR has already undone its original; continue at its link. */
			tx->undo_lsn = view->undo_next_lsn;
			break;
		case 24U:
			tx->undo_lsn = view->undo_next_lsn;
			break;
		case 25U:
			tx->state = RH_TX_PREPARED;
			break;
		case 26U:
			tx->state = RH_TX_COMMITTED;
			break;
		case 27U:
			tx->state = RH_TX_FORGOTTEN;
			break;
		case 28U:
			if (parse_dynamic_open_attribute(&records[i], view,
					attributes, capacity, &open_entry_size))
				goto out;
			++local_result.dynamic_open_attributes;
			break;
		case 10U:
			if (apply_delete_dirty_clusters(&records[i], view,
					dirty_pages, capacity))
				goto out;
			++local_result.delete_dirty_controls;
			break;
		case 23U:
			if (apply_hotfix(&records[i], view, dirty_pages, capacity,
					attributes, capacity, open_entry_size))
				goto out;
			++local_result.hotfix_controls;
			break;
		default:
			break;
		}
		if (operation_is_mutation(view->action_class)) {
			records[i].plan_flags |= RH_REPLAY_PLAN_REDO;
			++local_result.mutation_records;
		}
	}

	/* Follow each active transaction's exact undo-next chain. */
	for (i = 0; i < capacity; ++i) {
		struct rh_tx *tx = &transactions[i];
		uint64_t cursor;
		unsigned int steps = 0;

		if (!tx->present || tx->state != RH_TX_ACTIVE)
			continue;
		cursor = tx->undo_lsn;
		while (cursor) {
			struct rh_replay_analysis_record *record;
			struct rh_replay_action_view view;

			if (++steps > RH_REPLAY_MAX_ACTIONS)
				goto out;
			record = find_record_by_lsn(records, record_count, cursor);
			if (!record || rh_replay_guard_action(record->bytes, record->size,
					geometry, RH_REPLAY_SOURCE_UNKNOWN, &view) ||
				view.transaction_id != tx->id)
				goto out;
			if (view.undo_operation == 1U) {
				cursor = view.undo_next_lsn;
				continue;
			}
			if (!operation_is_mutation(view.action_class)) {
				if (view.action_class != RH_REPLAY_ACTION_CONTROL)
					goto out;
				cursor = view.undo_next_lsn;
				continue;
			}
			/* A loser mutation with Noop has no native before-image. */
			if (view.undo_operation == 0U)
				goto out;
			record->plan_flags |= RH_REPLAY_PLAN_UNDO;
			cursor = view.undo_next_lsn;
		}
	}
	/* No active mutation may be skipped by a forged/short undo-next chain. */
	for (i = 0; i < record_count; ++i) {
		struct rh_tx *tx;

		if (!operation_is_mutation(views[i].action_class))
			continue;
		tx = find_tx(transactions, capacity, views[i].transaction_id, 0);
		if (tx && tx->state == RH_TX_ACTIVE &&
			!(records[i].plan_flags & RH_REPLAY_PLAN_UNDO))
			goto out;
	}
	/* Bind every physical mutation to the final, reconstructed DPT mapping. */
	for (i = 0; i < record_count; ++i) {
		struct rh_dirty_page *page;
		uint32_t key;

		if (!operation_is_mutation(views[i].action_class) ||
			!(records[i].plan_flags & (RH_REPLAY_PLAN_REDO |
				RH_REPLAY_PLAN_UNDO)))
			continue;
		if (!checkpoint.present) {
			records[i].effective_lcn = views[i].first_lcn;
			records[i].has_effective_lcn = 1;
			continue;
		}
		key = rd16(records[i].bytes + 60);
		page = find_dirty_page(dirty_pages, capacity, key,
			views[i].target_vcn);
		if (!page || !page->lcn_valid ||
			page->oldest_lsn > views[i].this_lsn)
			goto out;
		records[i].effective_lcn = page->lcn;
		records[i].has_effective_lcn = 1;
	}

	for (i = 0; i < record_count; ++i) {
		if (records[i].plan_flags & RH_REPLAY_PLAN_UNDO) {
			++local_result.loser_redos;
			++local_result.loser_undos;
		} else if (records[i].plan_flags & RH_REPLAY_PLAN_REDO) {
			++local_result.winner_redos;
		}
	}
	if (checkpoint.present) {
		unsigned int j;
		for (j = 0; j < 4U; ++j)
			if (observed_table_lsn[j] != checkpoint.table_lsn[j] ||
				observed_table_length[j] != checkpoint.table_length[j])
				goto out;
	}
	if (consumer) {
		struct rh_replay_analysis_export completed;

		memset(&completed, 0, sizeof(completed));
		completed.records = records;
		completed.views = views;
		completed.record_count = record_count;
		completed.geometry = geometry;
		completed.synced_lsn = synced_lsn;
		completed.committed_lsn = committed_lsn;
		completed.analysis_start_lsn = analysis_start;
		completed.open_attributes = attributes;
		completed.open_attribute_capacity = capacity;
		completed.open_entry_size = open_entry_size;
		completed.result = &local_result;
		if (consumer(&completed, consumer_opaque))
			goto out;
	}
	if (result)
		*result = local_result;
	rc = 0;
out:
	free(dirty_pages);
	free(attributes);
	free(transactions);
	free(views);
	return rc;
}

int rh_replay_analysis_plan(struct rh_replay_analysis_record *records,
		size_t record_count, const struct rh_replay_geometry *geometry,
		uint64_t synced_lsn, uint64_t committed_lsn,
		struct rh_replay_analysis_result *result)
{
	return rh_replay_analysis_plan_export(records, record_count, geometry,
		synced_lsn, committed_lsn, NULL, NULL, result);
}
