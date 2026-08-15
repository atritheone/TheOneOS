/*
 * Bounded malformed-input tests for the roothealth-linked NTFS parser
 * hardening.  The qualification checker builds the selected library objects
 * with ASan/UBSan and globalizes only the three private functions named below
 * in its disposable object copies.  Production objects and symbols are not
 * changed.
 */

#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "attrib.h"
#include "index.h"
#include "inode.h"
#include "layout.h"
#include "runlist.h"
#include "types.h"
#include "volume.h"

#define RH_NTFS_SB_SIZE 4096U
#define RH_NODE_ENTRY_SIZE \
	((sizeof(INDEX_ENTRY_HEADER) + sizeof(VCN) + 7U) & ~(size_t)7U)

extern int ntfs_decompress(u8 *dest, u32 dest_size, u8 *cb_start,
		u32 cb_size);
extern INDEX_BLOCK *ntfs_ir_to_ib(INDEX_ROOT *ir, VCN ib_vcn);
extern int ntfs_ib_copy_tail(ntfs_index_context *icx, INDEX_BLOCK *src,
		INDEX_ENTRY *median, VCN new_vcn);

static unsigned int checks;

static void require(int condition, const char *message)
{
	checks++;
	if (!condition) {
		fprintf(stderr, "FAIL[%u]: %s (errno=%d)\n", checks, message,
			errno);
		exit(1);
	}
}

static INDEX_ENTRY *first_entry(INDEX_HEADER *ih)
{
	return (INDEX_ENTRY *)((u8 *)ih + le32_to_cpu(ih->entries_offset));
}

static void make_index_stream(INDEX_HEADER *ih, size_t buffer_size,
		u16 entry_length, u8 flags, u32 index_length)
{
	INDEX_ENTRY *ie;

	memset(ih, 0, buffer_size);
	ih->entries_offset = cpu_to_le32(sizeof(INDEX_HEADER));
	ih->index_length = cpu_to_le32(index_length);
	ih->allocated_size = cpu_to_le32(buffer_size);
	ie = first_entry(ih);
	ie->length = cpu_to_le16(entry_length);
	ie->ie_flags = flags;
}

static void test_index_streams(void)
{
	union {
		uint64_t align;
		u8 bytes[128];
	} storage;
	INDEX_HEADER *ih = (INDEX_HEADER *)storage.bytes;

	make_index_stream(ih, sizeof(storage.bytes), sizeof(INDEX_ENTRY_HEADER),
		INDEX_ENTRY_END, sizeof(INDEX_HEADER) +
		sizeof(INDEX_ENTRY_HEADER));
	require(!ntfs_ie_stream_inconsistent(ih, 17),
		"valid terminal index stream rejected");

	make_index_stream(ih, sizeof(storage.bytes), sizeof(INDEX_ENTRY_HEADER),
		0, sizeof(INDEX_HEADER) + sizeof(INDEX_ENTRY_HEADER));
	require(ntfs_ie_stream_inconsistent(ih, 17) < 0,
		"unterminated index stream accepted");

	make_index_stream(ih, sizeof(storage.bytes), 0, 0,
		sizeof(INDEX_HEADER) + sizeof(INDEX_ENTRY_HEADER));
	require(ntfs_ie_stream_inconsistent(ih, 17) < 0,
		"zero-length index entry accepted");

	make_index_stream(ih, sizeof(storage.bytes),
		sizeof(INDEX_ENTRY_HEADER) + 1, 0,
		sizeof(INDEX_HEADER) + sizeof(INDEX_ENTRY_HEADER) + 1);
	require(ntfs_ie_stream_inconsistent(ih, 17) < 0,
		"unaligned index entry accepted");

	make_index_stream(ih, sizeof(storage.bytes), sizeof(INDEX_ENTRY_HEADER),
		INDEX_ENTRY_END, sizeof(INDEX_HEADER) +
		2 * sizeof(INDEX_ENTRY_HEADER));
	require(ntfs_ie_stream_inconsistent(ih, 17) < 0,
		"early terminal index entry accepted");

	make_index_stream(ih, sizeof(storage.bytes), sizeof(INDEX_ENTRY_HEADER),
		0, sizeof(INDEX_HEADER) + sizeof(INDEX_ENTRY_HEADER) / 2);
	require(ntfs_ie_stream_inconsistent(ih, 17) < 0,
		"truncated index-entry header accepted");
}

static void test_index_attribute(void)
{
	union {
		uint64_t align;
		u8 bytes[256];
	} storage;
	ATTR_RECORD *attr = (ATTR_RECORD *)storage.bytes;
	INDEX_ROOT *ir;
	INDEX_ENTRY *ie;
	ntfs_volume vol;
	BOOL fixed;
	u16 value_offset = offsetof(ATTR_RECORD, resident_end);
	u32 value_length = sizeof(INDEX_ROOT) + sizeof(INDEX_ENTRY_HEADER);
	u32 attr_length = (value_offset + value_length + 7) & ~7U;

	memset(&vol, 0, sizeof(vol));
	vol.mft_record_size = 1024;
	vol.indx_record_size = 4096;

	memset(&storage, 0, sizeof(storage));
	attr->type = AT_INDEX_ROOT;
	attr->length = cpu_to_le32(attr_length);
	attr->value_offset = cpu_to_le16(value_offset);
	attr->value_length = cpu_to_le32(value_length);
	ir = (INDEX_ROOT *)(storage.bytes + value_offset);
	ir->index_block_size = cpu_to_le32(4096);
	ir->index.entries_offset = cpu_to_le32(sizeof(INDEX_HEADER));
	ir->index.index_length = cpu_to_le32(sizeof(INDEX_HEADER) +
		sizeof(INDEX_ENTRY_HEADER));
	ir->index.allocated_size = ir->index.index_length;
	ie = first_entry(&ir->index);
	ie->length = cpu_to_le16(sizeof(INDEX_ENTRY_HEADER));
	ie->ie_flags = INDEX_ENTRY_END;
	fixed = FALSE;
	require(!ntfs_attr_inconsistent(&vol, attr, 17, &fixed),
		"valid resident index root rejected");

	ir->index_block_size = cpu_to_le32(2048);
	errno = 0;
	require(ntfs_attr_inconsistent(&vol, attr, 17, &fixed) < 0 &&
		errno == EIO, "undersized INDEX_ROOT block size accepted");

	ir->index_block_size = cpu_to_le32(6144);
	errno = 0;
	require(ntfs_attr_inconsistent(&vol, attr, 17, &fixed) < 0 &&
		errno == EIO, "non-power-of-two INDEX_ROOT block size accepted");

	ir->index_block_size = cpu_to_le32(4096);
	ie->ie_flags = 0;
	errno = 0;
	require(ntfs_attr_inconsistent(&vol, attr, 17, &fixed) < 0 &&
		errno == EIO, "unterminated INDEX_ROOT stream accepted");
}

static void test_index_block_and_mutation_bounds(void)
{
	INDEX_BLOCK *ib;
	INDEX_ENTRY *ie;
	ntfs_volume vol;
	ntfs_inode ni;
	ntfs_attr ia;
	ntfs_index_context icx;
	INDEX_ROOT *ir;
	INDEX_BLOCK *src;
	INDEX_ENTRY *median;
	u8 *root_bytes;

	memset(&vol, 0, sizeof(vol));
	memset(&ni, 0, sizeof(ni));
	memset(&ia, 0, sizeof(ia));
	ni.vol = &vol;
	ni.mft_no = 17;
	ia.ni = &ni;

	ib = calloc(1, 4096);
	require(ib != NULL, "index block allocation failed");
	ib->magic = magic_INDX;
	ib->index_block_vcn = cpu_to_sle64(3);
	ib->index.entries_offset = cpu_to_le32(sizeof(INDEX_HEADER));
	ib->index.index_length = cpu_to_le32(sizeof(INDEX_HEADER) +
		sizeof(INDEX_ENTRY_HEADER));
	ib->index.allocated_size = cpu_to_le32(4096 -
		offsetof(INDEX_BLOCK, index));
	ie = first_entry(&ib->index);
	ie->length = cpu_to_le16(sizeof(INDEX_ENTRY_HEADER));
	ie->ie_flags = 0;
	require(ntfs_index_block_inconsistent(&vol, &ia, ib, 4096, 17, 3) < 0,
		"INDX block with unterminated stream accepted");
	free(ib);

	root_bytes = calloc(1, 8192);
	require(root_bytes != NULL, "large index root allocation failed");
	ir = (INDEX_ROOT *)root_bytes;
	ir->index_block_size = cpu_to_le32(512);
	ir->index.entries_offset = cpu_to_le32(sizeof(INDEX_HEADER));
	ir->index.index_length = cpu_to_le32(sizeof(INDEX_HEADER) + 4096);
	ie = first_entry(&ir->index);
	ie->length = cpu_to_le16(4096);
	ie->ie_flags = INDEX_ENTRY_END;
	errno = 0;
	require(ntfs_ir_to_ib(ir, 4) == NULL && errno == EIO,
		"oversized INDEX_ROOT copy reached destination memcpy");
	free(root_bytes);

	src = calloc(1, 4096);
	require(src != NULL, "source INDX allocation failed");
	src->index.entries_offset = cpu_to_le32(sizeof(INDEX_HEADER));
	src->index.index_length = cpu_to_le32(2000);
	median = first_entry(&src->index);
	median->length = cpu_to_le16(sizeof(INDEX_ENTRY_HEADER));
	memset(&icx, 0, sizeof(icx));
	icx.block_size = 512;
	errno = 0;
	require(ntfs_ib_copy_tail(&icx, src, median, 5) == STATUS_ERROR &&
		errno == EIO, "oversized INDX tail reached destination memcpy");
	free(src);
}

static void test_index_depth(void)
{
	union {
		uint64_t align;
		u8 bytes[sizeof(INDEX_ENTRY)];
	} storage;
	INDEX_ENTRY *ie = (INDEX_ENTRY *)storage.bytes;
	ntfs_index_context icx;
	sle64 vcn;

	memset(&storage, 0, sizeof(storage));
	memset(&icx, 0, sizeof(icx));
	ie->length = cpu_to_le16(RH_NODE_ENTRY_SIZE);
	ie->ie_flags = INDEX_ENTRY_NODE;
	vcn = cpu_to_sle64(1);
	memcpy(storage.bytes + RH_NODE_ENTRY_SIZE - sizeof(vcn), &vcn,
		sizeof(vcn));
	icx.is_in_root = FALSE;
	icx.pindex = MAX_PARENT_VCN - 1;
	errno = 0;
	require(ntfs_index_walk_down(ie, &icx) == NULL && errno == EOPNOTSUPP,
		"index walk exceeded fixed parent stack");
}

static ATTR_RECORD *make_mapping_attr(const u8 *stream, size_t stream_size,
		u8 **allocation)
{
	size_t mapping_offset = (sizeof(ATTR_RECORD) + 7) & ~(size_t)7;
	size_t total = mapping_offset + stream_size;
	ATTR_RECORD *attr;

	*allocation = calloc(1, total);
	if (!*allocation)
		return NULL;
	attr = (ATTR_RECORD *)*allocation;
	attr->type = AT_DATA;
	attr->length = cpu_to_le32(total);
	attr->non_resident = 1;
	attr->mapping_pairs_offset = cpu_to_le16(mapping_offset);
	attr->lowest_vcn = cpu_to_sle64(0);
	attr->highest_vcn = cpu_to_sle64(0);
	attr->allocated_size = cpu_to_sle64(4096);
	attr->data_size = cpu_to_sle64(4096);
	attr->initialized_size = cpu_to_sle64(4096);
	memcpy(*allocation + mapping_offset, stream, stream_size);
	return attr;
}

static runlist_element *decode_mapping(ntfs_volume *vol, const u8 *stream,
		size_t stream_size, u8 **allocation)
{
	ATTR_RECORD *attr = make_mapping_attr(stream, stream_size, allocation);

	if (!attr)
		return NULL;
	errno = 0;
	return ntfs_mapping_pairs_decompress(vol, attr, NULL);
}

static void require_mapping_rejected(ntfs_volume *vol, const u8 *stream,
		size_t stream_size, const char *message)
{
	u8 *allocation = NULL;
	runlist_element *rl = decode_mapping(vol, stream, stream_size,
		&allocation);

	require(!rl && errno == EIO, message);
	free(rl);
	free(allocation);
}

static void test_mapping_pairs(void)
{
	static const u8 valid[] = { 0x11, 0x01, 0x02, 0x00 };
	static const u8 signed_minus_one[] = {
		0x81, 0x01, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
		0x00
	};
	static const u8 width_nine[] = {
		0x91, 0x01, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
	};
	static const u8 truncated_length[] = { 0x01 };
	static const u8 truncated_offset[] = { 0x11, 0x01 };
	static const u8 vcn_overflow[] = {
		0x08, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x7f,
		0x01, 0x01, 0x00
	};
	static const u8 lcn_overflow[] = {
		0x81, 0x01, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x7f,
		0x11, 0x01, 0x01, 0x00
	};
	ntfs_volume vol;
	u8 *allocation = NULL;
	runlist_element *rl;

	memset(&vol, 0, sizeof(vol));
	vol.cluster_size = 4096;
	vol.cluster_size_bits = 12;
	vol.major_ver = 3;

	rl = decode_mapping(&vol, valid, sizeof(valid), &allocation);
	require(rl && rl[0].vcn == 0 && rl[0].lcn == 2 && rl[0].length == 1,
		"valid mapping pair decoded incorrectly");
	free(rl);
	free(allocation);
	allocation = NULL;

	rl = decode_mapping(&vol, signed_minus_one, sizeof(signed_minus_one),
		&allocation);
	require(rl && rl[0].lcn == LCN_HOLE && rl[0].length == 1,
		"eight-byte negative mapping delta was not sign-extended exactly");
	free(rl);
	free(allocation);

	require_mapping_rejected(&vol, width_nine, sizeof(width_nine),
		"nine-byte mapping delta accepted");
	require_mapping_rejected(&vol, truncated_length,
		sizeof(truncated_length), "truncated mapping length accepted");
	require_mapping_rejected(&vol, truncated_offset,
		sizeof(truncated_offset), "truncated mapping offset accepted");
	require_mapping_rejected(&vol, vcn_overflow, sizeof(vcn_overflow),
		"mapping VCN signed overflow accepted");
	require_mapping_rejected(&vol, lcn_overflow, sizeof(lcn_overflow),
		"mapping LCN signed overflow accepted");
}

static void test_compression(void)
{
	static u8 zero_header[] = { 0x00, 0x00 };
	static u8 one_byte[] = { 0x01 };
	static u8 truncated_phrase[] = {
		0x03, 0x80, 0x04, 0x41, 0x42, 0xcc
	};
	static u8 full_before_input_end[] = {
		0x04, 0x80, 0x02, 0x41, 0xfc, 0x0f, 0x42
	};
	u8 *dest = malloc(RH_NTFS_SB_SIZE);
	u8 byte = 0;

	require(dest != NULL, "compression destination allocation failed");
	memset(dest, 0xa5, RH_NTFS_SB_SIZE);
	require(!ntfs_decompress(dest, RH_NTFS_SB_SIZE, zero_header,
		sizeof(zero_header)) && dest[0] == 0 &&
		dest[RH_NTFS_SB_SIZE - 1] == 0,
		"zero terminator did not zero-fill output");

	errno = 0;
	require(ntfs_decompress(dest, RH_NTFS_SB_SIZE, one_byte,
		sizeof(one_byte)) < 0 && errno == EOVERFLOW,
		"one-byte sub-block header accepted");

	errno = 0;
	require(ntfs_decompress(dest, RH_NTFS_SB_SIZE, truncated_phrase,
		sizeof(truncated_phrase)) < 0 && errno == EOVERFLOW,
		"one-byte phrase token accepted");

	memset(dest, 0, RH_NTFS_SB_SIZE);
	require(!ntfs_decompress(dest, RH_NTFS_SB_SIZE, full_before_input_end,
		sizeof(full_before_input_end)) && dest[0] == 0x41 &&
		dest[RH_NTFS_SB_SIZE - 1] == 0x41,
		"full output slot did not skip remaining compressed bytes");

	require(!ntfs_decompress(&byte, 0, one_byte, sizeof(one_byte)),
		"zero-length output read a partial compressed header");
	free(dest);
}

int main(void)
{
	test_index_streams();
	test_index_attribute();
	test_index_block_and_mutation_bounds();
	test_index_depth();
	test_mapping_pairs();
	test_compression();
	printf("PASS %u bounded corrupt-input checks\n", checks);
	return 0;
}
