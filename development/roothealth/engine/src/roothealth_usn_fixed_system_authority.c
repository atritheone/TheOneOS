/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) ROOTHEALTH_IO_ROLE(READER) */
#include "config.h"

#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "endians.h"
#include "layout.h"
#include "roothealth_census_device.h"
#include "roothealth_complete_census.h"
#include "roothealth_coverage.h"
#include "roothealth_free_slot_authority_internal.h"
#include "roothealth_hash_stream.h"
#include "roothealth_mft_bitmap.h"
#include "roothealth_namespace.h"
#include "roothealth_raw_mft.h"
#include "roothealth_usn_fixed_system_authority.h"
#include "roothealth_usn_fixed_system_authority_internal.h"

#define RH_USN_FIXED_SYSTEM_MAGIC UINT64_C(0x524855534e464958)
#define RH_ROLE_PRESENT 1U
#define RH_ROLE_ABSENT 2U

struct rh_fixed_role {
	uint8_t state;
	struct rh_free_slot_reference reference;
};

struct rh_usn_fixed_system_authority_census {
	uint64_t magic;
	uint64_t volume_serial;
	struct rh_usn_fixed_system_authority_view view;
	unsigned char raw_census_hash[32];
	unsigned char namespace_census_hash[32];
	unsigned char mft_bitmap_census_hash[32];
	struct rh_fixed_role roles[RH_USN_FIXED_SYSTEM_ROLE_COUNT];
	struct rh_free_slot_reference *references;
	size_t reference_count;
	unsigned char integrity_hash[32];
};

static const char *const rh_role_ids[RH_USN_FIXED_SYSTEM_ROLE_COUNT] = {
	"extend.objid",
	"extend.quota",
	"extend.reparse",
	"extend.roothealth",
	"extend.usnjrnl",
	"system.attrdef",
	"system.badclus",
	"system.bitmap",
	"system.boot",
	"system.extend",
	"system.logfile",
	"system.mft",
	"system.mftmirr",
	"system.root",
	"system.secure",
	"system.upcase",
	"system.volume",
};

struct rh_system_role_spec {
	size_t role;
	uint64_t record;
	const char *name;
	int directory;
};

static const struct rh_system_role_spec rh_system_roles[] = {
	{5U, 4U, "$AttrDef", 0},
	{6U, 8U, "$BadClus", 0},
	{7U, 6U, "$Bitmap", 0},
	{8U, 7U, "$Boot", 0},
	{9U, 11U, "$Extend", 1},
	{10U, 2U, "$LogFile", 0},
	{11U, 0U, "$MFT", 0},
	{12U, 1U, "$MFTMirr", 0},
	{13U, 5U, ".", 1},
	{14U, 9U, "$Secure", 0},
	{15U, 10U, "$UpCase", 0},
	{16U, 3U, "$Volume", 0},
};

static int rh_hash_nonzero(const unsigned char digest[32])
{
	size_t i;

	for (i = 0; i < 32U; i++)
		if (digest[i])
			return 1;
	return 0;
}

static int rh_h_bytes(struct rh_hash_stream *hash, const void *bytes,
		size_t length)
{
	return rh_hash_stream_update(hash, bytes, length);
}

static int rh_h_u8(struct rh_hash_stream *hash, uint8_t value)
{
	return rh_h_bytes(hash, &value, sizeof(value));
}

static int rh_h_u16(struct rh_hash_stream *hash, uint16_t value)
{
	unsigned char bytes[2] = {
		(unsigned char)value, (unsigned char)(value >> 8)
	};

	return rh_h_bytes(hash, bytes, sizeof(bytes));
}

static int rh_h_u32(struct rh_hash_stream *hash, uint32_t value)
{
	unsigned char bytes[4];
	unsigned int i;

	for (i = 0; i < 4U; i++)
		bytes[i] = (unsigned char)(value >> (8U * i));
	return rh_h_bytes(hash, bytes, sizeof(bytes));
}

static int rh_h_u64(struct rh_hash_stream *hash, uint64_t value)
{
	unsigned char bytes[8];
	unsigned int i;

	for (i = 0; i < 8U; i++)
		bytes[i] = (unsigned char)(value >> (8U * i));
	return rh_h_bytes(hash, bytes, sizeof(bytes));
}

static int rh_reference_compare(const void *left_pointer,
		const void *right_pointer)
{
	const struct rh_free_slot_reference *left = left_pointer;
	const struct rh_free_slot_reference *right = right_pointer;

	if (left->record != right->record)
		return left->record < right->record ? -1 : 1;
	if (left->sequence != right->sequence)
		return left->sequence < right->sequence ? -1 : 1;
	return 0;
}

static int rh_digest_matches_hex(const unsigned char digest[32],
		const char *expected)
{
	static const char hex[] = "0123456789abcdef";
	char actual[65];
	size_t i;

	for (i = 0; i < 32U; i++) {
		actual[2U * i] = hex[digest[i] >> 4];
		actual[2U * i + 1U] = hex[digest[i] & 15U];
	}
	actual[64] = 0;
	return !strcmp(actual, expected);
}

static int rh_raw_ref_valid(const struct rh_raw_mft_census *raw,
		struct rh_free_slot_reference reference, int directory)
{
	const struct rh_raw_mft_slot *slot;

	if (!reference.sequence || reference.record >= raw->slot_count)
		return 0;
	slot = &raw->slots[reference.record];
	return slot->state == RH_RAW_SLOT_LIVE_BASE &&
		slot->sequence == reference.sequence &&
		(directory < 0 || !!(slot->flags &
			le16_to_cpu(MFT_RECORD_IS_DIRECTORY)) == directory);
}

static int rh_inputs_ready(uint64_t volume_serial, uint64_t generation,
		const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *ns,
		const struct rh_mft_bitmap_census *mft)
{
	return volume_serial && generation && raw && ns && mft && raw->slots &&
		raw->generation == generation && ns->generation == generation &&
		mft->generation == generation && raw->records_complete &&
		raw->records_bounded && raw->layout_complete &&
		raw->attribute_lists_complete && raw->extents_complete &&
		raw->slots_completed == raw->slots_expected &&
		raw->slot_count == raw->slots_expected && !raw->unreadable_records &&
		!raw->invalid_records && !raw->layout_candidate_count &&
		raw->opaque_records == raw->opaque_slot_count &&
		(!raw->opaque_slot_count || raw->opaque_slots_complete) &&
		ns->graph_bounded && ns->graph_complete && ns->i30_complete &&
		ns->reciprocity_complete && ns->identity_checked &&
		ns->identity != RH_T1OS_IDENTITY_UNKNOWN &&
		ns->links_completed == ns->links_expected &&
		ns->link_count == raw->file_name_count &&
		ns->i30_edge_count == ns->link_count && !ns->orphan_nodes &&
		!ns->unresolved_parents && !ns->cycles && !ns->aliases &&
		!ns->i30_bitmap_changes && !ns->i30_clear_bits_required &&
		mft->complete && mft->structurally_valid &&
		mft->mft_slots_expected == raw->slots_expected &&
		mft->mft_slots_completed == raw->slots_expected &&
		mft->mft_slots_in_use + mft->mft_slots_free == raw->slots_expected &&
		!mft->unreadable_slots && !mft->ambiguous_slots &&
		rh_hash_nonzero(raw->census_hash) &&
		rh_hash_nonzero(ns->census_hash) &&
		rh_hash_nonzero(mft->census_hash);
}

static int rh_stream_payload_hash(const struct rh_census_reader *reader,
		const struct rh_raw_mft_census *raw, uint64_t record,
		uint16_t sequence, uint64_t expected_size, unsigned char digest[32])
{
	struct rh_raw_mft_ref owner;
	const struct rh_raw_attribute *base = NULL;
	struct rh_hash_stream hash;
	unsigned char buffer[65536];
	uint64_t offset = 0;
	size_t i;

	owner.record = record;
	owner.sequence = sequence;
	for (i = 0; i < raw->attribute_count; i++) {
		const struct rh_raw_attribute *attribute = &raw->attributes[i];

		if (attribute->owner.record != record ||
				attribute->owner.sequence != sequence ||
				attribute->type != le32_to_cpu(AT_DATA) ||
				attribute->name_length || !attribute->nonresident ||
				attribute->lowest_vcn)
			continue;
		if (base) {
			errno = EPERM;
			return -1;
		}
		base = attribute;
	}
	if (!base || base->data_size < 0 || base->initialized_size < 0 ||
			(uint64_t)base->data_size != expected_size ||
			(uint64_t)base->initialized_size != expected_size) {
		errno = EPERM;
		return -1;
	}
	rh_hash_stream_init(&hash);
	while (offset < expected_size) {
		size_t part = sizeof(buffer);

		if ((uint64_t)part > expected_size - offset)
			part = (size_t)(expected_size - offset);
		if (rh_raw_mft_stream_pread_reader(reader, raw, owner,
				le32_to_cpu(AT_DATA), NULL, 0U, offset, part, buffer) ||
				rh_hash_stream_update(&hash, buffer, part))
			return -1;
		offset += part;
	}
	return rh_hash_stream_final(&hash, digest);
}

static int rh_set_role(struct rh_usn_fixed_system_authority_census *census,
		size_t role, uint8_t state, struct rh_raw_mft_ref reference)
{
	if (role >= RH_USN_FIXED_SYSTEM_ROLE_COUNT ||
			(state != RH_ROLE_PRESENT && state != RH_ROLE_ABSENT) ||
			(state == RH_ROLE_ABSENT &&
			 (reference.record || reference.sequence)) ||
			(state == RH_ROLE_PRESENT && !reference.sequence)) {
		errno = EINVAL;
		return -1;
	}
	census->roles[role].state = state;
	census->roles[role].reference.record = reference.record;
	census->roles[role].reference.sequence = reference.sequence;
	if (state == RH_ROLE_PRESENT) {
		census->view.present_role_mask |= UINT32_C(1) << role;
		census->view.fixed_roles_present++;
		census->view.reference_fields_examined++;
	} else {
		census->view.absent_role_mask |= UINT32_C(1) << role;
	}
	census->view.fixed_roles_completed++;
	return 0;
}

static int rh_resolve_required_role(
		struct rh_usn_fixed_system_authority_census *census,
		const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *ns, size_t role,
		struct rh_raw_mft_ref parent, const char *name, int directory,
		uint64_t expected_record, uint16_t expected_sequence)
{
	struct rh_namespace_resolved_child child;
	struct rh_raw_mft_ref reference;

	if (rh_namespace_resolve_exact_child(raw, ns, parent, name, directory,
			&child) || child.state != RH_NAMESPACE_CHILD_PRESENT ||
			child.child.record != expected_record ||
			child.child.sequence != expected_sequence) {
		errno = EPERM;
		return -1;
	}
	reference = child.child;
	return rh_set_role(census, role, RH_ROLE_PRESENT, reference);
}

static int rh_hash_roles(struct rh_usn_fixed_system_authority_census *census)
{
	struct rh_hash_stream hash;
	size_t i;

	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHFIXR1", 8U) ||
			rh_h_u32(&hash, RH_USN_FIXED_SYSTEM_AUTHORITY_VERSION) ||
			rh_h_u64(&hash, RH_USN_FIXED_SYSTEM_ROLE_COUNT))
		return -1;
	for (i = 0; i < RH_USN_FIXED_SYSTEM_ROLE_COUNT; i++) {
		const char *required = rh_coverage_required_fixed_check_id(i);
		size_t bytes = strlen(rh_role_ids[i]);

		if (!required || strcmp(required, rh_role_ids[i]) ||
				bytes > UINT16_MAX || rh_h_u16(&hash, (uint16_t)bytes) ||
				rh_h_bytes(&hash, rh_role_ids[i], bytes) ||
				rh_h_u8(&hash, census->roles[i].state) ||
				rh_h_u64(&hash, census->roles[i].reference.record) ||
				rh_h_u16(&hash, census->roles[i].reference.sequence)) {
			errno = EIO;
			return -1;
		}
	}
	return rh_hash_stream_final(&hash, census->view.role_manifest_hash);
}

static int rh_build_reference_manifest(
		struct rh_usn_fixed_system_authority_census *census)
{
	struct rh_hash_stream hash;
	struct rh_free_slot_reference temporary[RH_USN_FIXED_SYSTEM_ROLE_COUNT];
	size_t count = 0, unique = 0, i;

	for (i = 0; i < RH_USN_FIXED_SYSTEM_ROLE_COUNT; i++)
		if (census->roles[i].state == RH_ROLE_PRESENT)
			temporary[count++] = census->roles[i].reference;
	qsort(temporary, count, sizeof(*temporary), rh_reference_compare);
	for (i = 0; i < count; i++) {
		if (unique && !rh_reference_compare(&temporary[unique - 1U],
				&temporary[i])) {
			errno = EPERM;
			return -1;
		}
		temporary[unique++] = temporary[i];
	}
	if (unique) {
		census->references = malloc(unique * sizeof(*census->references));
		if (!census->references)
			return -1;
		memcpy(census->references, temporary,
			unique * sizeof(*census->references));
	}
	census->reference_count = unique;
	census->view.unique_references = unique;
	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHFREF1", 8U) || rh_h_u64(&hash, unique))
		return -1;
	for (i = 0; i < unique; i++)
		if (rh_h_u64(&hash, census->references[i].record) ||
				rh_h_u16(&hash, census->references[i].sequence))
			return -1;
	return rh_hash_stream_final(&hash,
		census->view.reference_manifest_hash);
}

static int rh_hash_evidence(
		struct rh_usn_fixed_system_authority_census *census,
		const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *ns,
		const struct rh_mft_bitmap_census *mft)
{
	struct rh_hash_stream hash;

	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHUFS1\0", 8U) ||
			rh_h_u32(&hash, RH_USN_FIXED_SYSTEM_AUTHORITY_VERSION) ||
			rh_h_u64(&hash, census->volume_serial) ||
			rh_h_u64(&hash, census->view.fixed_roles_expected) ||
			rh_h_u64(&hash, census->view.fixed_roles_completed) ||
			rh_h_u64(&hash, census->view.fixed_roles_present) ||
			rh_h_u64(&hash, census->view.usn_records_expected) ||
			rh_h_u64(&hash, census->view.usn_records_completed) ||
			rh_h_u64(&hash, census->view.reference_fields_examined) ||
			rh_h_u32(&hash, (uint32_t)census->view.usn_state) ||
			rh_h_u64(&hash, census->view.usn_reference.record) ||
			rh_h_u16(&hash, census->view.usn_reference.sequence) ||
			rh_h_bytes(&hash, raw->census_hash, 32U) ||
			rh_h_bytes(&hash, ns->census_hash, 32U) ||
			rh_h_bytes(&hash, mft->census_hash, 32U) ||
			rh_h_bytes(&hash, census->view.attrdef_payload_hash, 32U) ||
			rh_h_bytes(&hash, census->view.upcase_payload_hash, 32U) ||
			rh_h_bytes(&hash, census->view.role_manifest_hash, 32U) ||
			rh_h_bytes(&hash, census->view.reference_manifest_hash, 32U))
		return -1;
	return rh_hash_stream_final(&hash, census->view.evidence_hash);
}

static int rh_integrity_hash(
		const struct rh_usn_fixed_system_authority_census *census,
		unsigned char output[32])
{
	struct rh_hash_stream hash;
	size_t i;

	rh_hash_stream_init(&hash);
	if (rh_h_bytes(&hash, "RHUFSA1", 8U) ||
			rh_h_u64(&hash, census->volume_serial) ||
			rh_h_u32(&hash, census->view.version) ||
			rh_h_u64(&hash, census->view.correlation_generation) ||
			rh_h_u64(&hash, census->view.fixed_roles_expected) ||
			rh_h_u64(&hash, census->view.fixed_roles_completed) ||
			rh_h_u64(&hash, census->view.fixed_roles_present) ||
			rh_h_u64(&hash, census->view.usn_records_expected) ||
			rh_h_u64(&hash, census->view.usn_records_completed) ||
			rh_h_u64(&hash, census->view.reference_fields_examined) ||
			rh_h_u64(&hash, census->view.unique_references) ||
			rh_h_u32(&hash, (uint32_t)census->view.usn_state) ||
			rh_h_u64(&hash, census->view.usn_reference.record) ||
			rh_h_u16(&hash, census->view.usn_reference.sequence) ||
			rh_h_u32(&hash, census->view.present_role_mask) ||
			rh_h_u32(&hash, census->view.absent_role_mask) ||
			rh_h_bytes(&hash, census->view.attrdef_payload_hash, 32U) ||
			rh_h_bytes(&hash, census->view.upcase_payload_hash, 32U) ||
			rh_h_bytes(&hash, census->view.role_manifest_hash, 32U) ||
			rh_h_bytes(&hash, census->view.reference_manifest_hash, 32U) ||
			rh_h_bytes(&hash, census->view.evidence_hash, 32U) ||
			rh_h_u8(&hash, census->view.complete) ||
			rh_h_bytes(&hash, census->raw_census_hash, 32U) ||
			rh_h_bytes(&hash, census->namespace_census_hash, 32U) ||
			rh_h_bytes(&hash, census->mft_bitmap_census_hash, 32U) ||
			rh_h_u64(&hash, census->reference_count))
		return -1;
	for (i = 0; i < census->reference_count; i++)
		if (rh_h_u64(&hash, census->references[i].record) ||
				rh_h_u16(&hash, census->references[i].sequence))
			return -1;
	return rh_hash_stream_final(&hash, output);
}

static int rh_census_valid(
		const struct rh_usn_fixed_system_authority_census *census)
{
	unsigned char digest[32];
	size_t i;

	if (!census || census->magic != RH_USN_FIXED_SYSTEM_MAGIC ||
			census->view.version != RH_USN_FIXED_SYSTEM_AUTHORITY_VERSION ||
			!census->volume_serial || !census->view.correlation_generation ||
			!census->view.complete ||
			census->view.fixed_roles_expected !=
				RH_USN_FIXED_SYSTEM_ROLE_COUNT ||
			census->view.fixed_roles_completed !=
				census->view.fixed_roles_expected ||
			census->view.usn_state != RH_FREE_SLOT_USN_ABSENT ||
			census->view.usn_reference.record ||
			census->view.usn_reference.sequence ||
			census->view.usn_records_expected ||
			census->view.usn_records_completed ||
			census->view.unique_references != census->reference_count ||
			census->reference_count > census->view.fixed_roles_completed ||
			(census->reference_count && !census->references) ||
			!rh_hash_nonzero(census->view.attrdef_payload_hash) ||
			!rh_hash_nonzero(census->view.upcase_payload_hash) ||
			!rh_hash_nonzero(census->view.role_manifest_hash) ||
			!rh_hash_nonzero(census->view.reference_manifest_hash) ||
			!rh_hash_nonzero(census->view.evidence_hash) ||
			!rh_hash_nonzero(census->raw_census_hash) ||
			!rh_hash_nonzero(census->namespace_census_hash) ||
			!rh_hash_nonzero(census->mft_bitmap_census_hash))
		return 0;
	for (i = 0; i < census->reference_count; i++)
		if (!census->references[i].sequence || (i &&
				rh_reference_compare(&census->references[i - 1U],
					&census->references[i]) >= 0))
			return 0;
	return !rh_integrity_hash(census, digest) &&
		!memcmp(digest, census->integrity_hash, sizeof(digest));
}

int rh_usn_fixed_system_authority_census_run(
		const struct rh_census_reader *reader, uint64_t volume_serial,
		uint64_t generation, const struct rh_raw_mft_census *raw,
		const struct rh_namespace_census *ns,
		const struct rh_mft_bitmap_census *mft,
		struct rh_usn_fixed_system_authority_census **output)
{
	static const char attrdef_hash[] =
		"d7de5b1b2f79f45f235ceb1adbc46908ed64eae174eb90ed66aefe5f25165da3";
	static const char upcase_hash[] =
		"41c26bc7a12bdaeb26025c93118697c7e3ef81ee048b00fe5cce2a472e0e0742";
	struct rh_usn_fixed_system_authority_census *census = NULL;
	struct rh_namespace_resolved_child child;
	struct rh_raw_mft_ref root, extend, zero = {0, 0};
	unsigned char boot[512];
	uint64_t reader_serial = 0;
	size_t i;

	if (output)
		*output = NULL;
	if (!output || !reader || !rh_inputs_ready(volume_serial, generation,
			raw, ns, mft) || rh_census_reader_read_exact(reader, 0,
			sizeof(boot), boot)) {
		if (!errno)
			errno = EPERM;
		return -1;
	}
	for (i = 0; i < 8U; i++)
		reader_serial |= (uint64_t)boot[72U + i] << (8U * i);
	if (reader_serial != volume_serial) {
		errno = EPERM;
		return -1;
	}
	census = calloc(1, sizeof(*census));
	if (!census)
		return -1;
	census->volume_serial = volume_serial;
	census->view.version = RH_USN_FIXED_SYSTEM_AUTHORITY_VERSION;
	census->view.correlation_generation = generation;
	census->view.fixed_roles_expected = RH_USN_FIXED_SYSTEM_ROLE_COUNT;
	census->view.usn_state = RH_FREE_SLOT_USN_ABSENT;
	memcpy(census->raw_census_hash, raw->census_hash, 32U);
	memcpy(census->namespace_census_hash, ns->census_hash, 32U);
	memcpy(census->mft_bitmap_census_hash, mft->census_hash, 32U);
	root.record = 5U;
	root.sequence = raw->slots[5U].sequence;
	extend.record = 11U;
	extend.sequence = raw->slots[11U].sequence;
	if (!rh_raw_ref_valid(raw, (struct rh_free_slot_reference){
			root.record, root.sequence}, 1) || !rh_raw_ref_valid(raw,
			(struct rh_free_slot_reference){extend.record, extend.sequence}, 1)) {
		errno = EPERM;
		goto fail;
	}
	for (i = 0; i < sizeof(rh_system_roles) / sizeof(rh_system_roles[0]);
			i++) {
		const struct rh_system_role_spec *role = &rh_system_roles[i];

		uint16_t sequence = raw->slots[role->record].sequence;

		if (!rh_raw_ref_valid(raw, (struct rh_free_slot_reference){
				role->record, sequence}, role->directory) ||
				rh_resolve_required_role(census, raw, ns, role->role, root,
					role->name, role->directory, role->record,
					sequence))
			goto fail;
	}
	if (rh_namespace_resolve_exact_child(raw, ns, extend, "$ObjId", 0,
			&child) || child.state != RH_NAMESPACE_CHILD_PRESENT ||
			rh_set_role(census, 0U, RH_ROLE_PRESENT, child.child) ||
			rh_namespace_resolve_exact_child(raw, ns, extend, "$Quota", 0,
				&child) || child.state != RH_NAMESPACE_CHILD_PRESENT ||
			rh_set_role(census, 1U, RH_ROLE_PRESENT, child.child) ||
			rh_namespace_resolve_exact_child(raw, ns, extend, "$Reparse", 0,
				&child) || child.state != RH_NAMESPACE_CHILD_PRESENT ||
			rh_set_role(census, 2U, RH_ROLE_PRESENT, child.child)) {
		errno = EPERM;
		goto fail;
	}
	if (rh_namespace_resolve_exact_child(raw, ns, extend, "$RootHealth", 0,
			&child))
		goto fail;
	if (mft->roothealth_record == RH_MFT_BITMAP_NO_ROOTHEALTH) {
		if (child.state != RH_NAMESPACE_CHILD_ABSENT ||
				rh_set_role(census, 3U, RH_ROLE_ABSENT, zero)) {
			errno = EPERM;
			goto fail;
		}
	} else {
		if (!mft->roothealth_record_bound || !mft->roothealth_sequence ||
				child.state != RH_NAMESPACE_CHILD_PRESENT ||
				child.child.record != mft->roothealth_record ||
				child.child.sequence != mft->roothealth_sequence ||
				rh_set_role(census, 3U, RH_ROLE_PRESENT, child.child)) {
			errno = EPERM;
			goto fail;
		}
	}
	if (rh_namespace_resolve_exact_child(raw, ns, extend, "$UsnJrnl", 0,
			&child))
		goto fail;
	if (child.state != RH_NAMESPACE_CHILD_ABSENT) {
		errno = EOPNOTSUPP;
		goto fail;
	}
	if (rh_set_role(census, 4U, RH_ROLE_ABSENT, zero) ||
			rh_stream_payload_hash(reader, raw, 4U,
				raw->slots[4U].sequence, 2560U,
				census->view.attrdef_payload_hash) ||
			rh_stream_payload_hash(reader, raw, 10U,
				raw->slots[10U].sequence, 131072U,
				census->view.upcase_payload_hash) ||
			!rh_digest_matches_hex(census->view.attrdef_payload_hash,
				attrdef_hash) ||
			!rh_digest_matches_hex(census->view.upcase_payload_hash,
				upcase_hash) || rh_hash_roles(census) ||
			rh_build_reference_manifest(census) ||
			rh_hash_evidence(census, raw, ns, mft)) {
		if (!errno)
			errno = EPERM;
		goto fail;
	}
	census->view.complete = 1U;
	census->magic = RH_USN_FIXED_SYSTEM_MAGIC;
	if (rh_integrity_hash(census, census->integrity_hash) ||
			!rh_census_valid(census)) {
		errno = EIO;
		goto fail;
	}
	*output = census;
	return 0;
fail:
	rh_usn_fixed_system_authority_census_destroy(census);
	return -1;
}

void rh_usn_fixed_system_authority_census_destroy(
		struct rh_usn_fixed_system_authority_census *census)
{
	if (!census)
		return;
	free(census->references);
	memset(census, 0, sizeof(*census));
	free(census);
}

static int rh_usn_fixed_system_authority_census_get_view(
		const struct rh_usn_fixed_system_authority_census *census,
		struct rh_usn_fixed_system_authority_view *view)
{
	if (!view || !rh_census_valid(census)) {
		errno = EINVAL;
		return -1;
	}
	*view = census->view;
	return 0;
}

static int rh_usn_fixed_system_component_seal_create(
		const struct rh_usn_fixed_system_authority_census *census,
		struct rh_free_slot_component_seal **output)
{
	if (output)
		*output = NULL;
	if (!output || !rh_census_valid(census)) {
		errno = EINVAL;
		return -1;
	}
	return rh_free_slot_friend_usn_fixed_system_seal(
		census->view.correlation_generation, census->view.usn_state, NULL,
		census->view.fixed_roles_expected,
		census->view.fixed_roles_completed, census->view.evidence_hash,
		census->references, census->reference_count, output);
}

int rh_complete_census_usn_fixed_system_get_view(
		const struct rh_complete_census *complete,
		struct rh_usn_fixed_system_authority_view *view)
{
	if (!complete || complete->version != RH_COMPLETE_CENSUS_VERSION ||
			!complete->usn_fixed_system_authority ||
			complete->generation != complete->
				usn_fixed_system_authority->view.correlation_generation ||
			complete->volume_serial !=
				complete->usn_fixed_system_authority->volume_serial ||
			memcmp(complete->raw.census_hash, complete->
				usn_fixed_system_authority->raw_census_hash, 32U) ||
			memcmp(complete->namespace_census.census_hash, complete->
				usn_fixed_system_authority->namespace_census_hash, 32U) ||
			memcmp(complete->mft_bitmap.census_hash, complete->
				usn_fixed_system_authority->mft_bitmap_census_hash, 32U)) {
		errno = EPERM;
		return -1;
	}
	return rh_usn_fixed_system_authority_census_get_view(
		complete->usn_fixed_system_authority, view);
}

int rh_complete_census_usn_fixed_system_component_seal_create(
		const struct rh_complete_census *complete,
		struct rh_free_slot_component_seal **output)
{
	if (output)
		*output = NULL;
	if (!output || !complete ||
			rh_complete_census_usn_fixed_system_get_view(complete,
				&(struct rh_usn_fixed_system_authority_view){0})) {
		errno = EPERM;
		return -1;
	}
	return rh_usn_fixed_system_component_seal_create(
		complete->usn_fixed_system_authority, output);
}
