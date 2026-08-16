#ifndef ROOTHEALTH_RECOVER_H
#define ROOTHEALTH_RECOVER_H

/*
 *		Declarations for processing log data
 *
 * Copyright (c) 2000-2005 Anton Altaparmakov
 * Copyright (c) 2014-2016 Jean-Pierre Andre
 */

/*
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program (in the main directory of the NTFS-3G
 * distribution in the file COPYING); if not, write to the Free Software
 * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
 */

#define getle16(p,x) le16_to_cpu(*(const le16*)((const char*)(p) + (x)))
#define getle32(p,x) le32_to_cpu(*(const le32*)((const char*)(p) + (x)))
#define getle64(p,x) le64_to_cpu(*(const le64*)((const char*)(p) + (x)))

#define feedle16(p,x) (*(const le16*)((const char*)(p) + (x)))
#define feedle32(p,x) (*(const le32*)((const char*)(p) + (x)))
#define feedle64(p,x) (*(const le64*)((const char*)(p) + (x)))

#include "types.h"
#include "volume.h"
#include "inode.h"
#include "attrib.h"
#include "logfile.h"
#include "roothealth_write.h"

enum ACTIONS {
	Noop,					/* 0 */
	CompensationlogRecord,			/* 1 */
	InitializeFileRecordSegment,		/* 2 */
	DeallocateFileRecordSegment,		/* 3 */
	WriteEndofFileRecordSegment,		/* 4 */
	CreateAttribute,			/* 5 */
	DeleteAttribute,			/* 6 */
	UpdateResidentValue,			/* 7 */
	UpdateNonResidentValue,			/* 8 */
	UpdateMappingPairs,			/* 9 */
	DeleteDirtyClusters,			/* 10 */
	SetNewAttributeSizes,			/* 11 */
	AddIndexEntryRoot,			/* 12 */
	DeleteIndexEntryRoot,			/* 13 */
	AddIndexEntryAllocation,		/* 14 */
	DeleteIndexEntryAllocation,		/* 15 */
	WriteEndOfIndexBuffer,			/* 16 */
	SetIndexEntryVcnRoot,			/* 17 */
	SetIndexEntryVcnAllocation,		/* 18 */
	UpdateFileNameRoot,			/* 19 */
	UpdateFileNameAllocation,		/* 20 */
	SetBitsInNonResidentBitMap,		/* 21 */
	ClearBitsInNonResidentBitMap,		/* 22 */
	HotFix,					/* 23 */
	EndTopLevelAction,			/* 24 */
	PrepareTransaction,			/* 25 */
	CommitTransaction,			/* 26 */
	ForgetTransaction,			/* 27 */
	OpenNonResidentAttribute,		/* 28 */
	OpenAttributeTableDump,			/* 29 */
	AttributeNamesDump,			/* 30 */
	DirtyPageTableDump,			/* 31 */
	TransactionTableDump,			/* 32 */
	UpdateRecordDataRoot,			/* 33 */
	UpdateRecordDataAllocation,		/* 34 */
	UpdateRelativeDataInIndex,		/* 35 */
	UpdateRelativeDataInIndex2,		/* 36 */
	ZeroEndOfFileRecord,			/* 37 */
	LastAction				/* 38 */
} ;

struct BUFFER {
	unsigned int num;
	unsigned int rnum;
	unsigned int size;
	unsigned int headsz;
	BOOL safe;
	union {
		u64 alignment;
		RESTART_PAGE_HEADER restart;
		RECORD_PAGE_HEADER record;
		char data[1];
	} block;  /* variable length, keep at the end */
} ;

struct ACTION_RECORD {
	struct ACTION_RECORD *next;
	struct ACTION_RECORD *prev;
	int num;
	unsigned int flags;
	LOG_RECORD record; /* variable length, keep at the end */
} ;

enum {		/* Flag values for ACTION_RECORD */
	ACTION_TO_REDO = 1,	/* Committed, possibly not synced */
	ACTION_TO_UNDO = 2	/* Active/loser transaction */
	} ;

struct ATTR {
	u64 inode;
	u64 reference;
	u64 lsn;
	u32 bytes_per_index;
	le32 type;
	u16 key;
	u16 namelen;
	le16 name[1];
} ;

extern u32 clustersz;
extern int clusterbits;
extern u32 blocksz;
extern int blockbits;
extern u16 bytespersect;
extern u64 mftlcn;
extern u32 mftrecsz;
extern int mftrecbits;
extern u32 mftcnt; /* number of entries */
extern BOOL optc;
extern BOOL optn;
extern int opts;
extern int optv;
extern unsigned int redocount;
extern unsigned int undocount;
extern ntfs_inode *log_ni;
extern ntfs_attr *log_na;
extern u64 logfilelcn;
extern u32 logfilesz; /* bytes */
extern u64 redos_met;
extern u64 committed_lsn;
extern u64 synced_lsn;
extern u64 latest_lsn;
extern u64 restart_lsn;

enum rh_native_log_state {
	RH_NATIVE_LOG_UNKNOWN = 0,
	RH_NATIVE_LOG_CLEAN_RESTART,
	RH_NATIVE_LOG_REPLAY_PLANNED,
	RH_NATIVE_LOG_EMPTY_T1OS
};

struct rh_log_result {
	enum rh_native_log_state state;
	int checked;
	int major_version;
	int minor_version;
	u64 logfile_bytes;
	u64 restart_lsn;
	u64 synced_lsn;
	u64 committed_lsn;
	u64 latest_lsn;
	unsigned int pages_expected;
	unsigned int pages_examined;
	unsigned int wiped_pages_scanned;
	unsigned int checkpoint_records_examined;
	unsigned int control_records_examined;
	unsigned int mutation_records_examined;
	unsigned int open_attribute_tables;
	unsigned int attribute_name_tables;
	unsigned int dirty_page_tables;
	unsigned int transaction_tables;
	unsigned int actions_seen;
	unsigned int redo_actions;
	unsigned int undo_actions;
	unsigned int restart_pages_planned;
	unsigned int unsupported_actions;
	unsigned int io_errors;
	unsigned int parse_errors;
	size_t planned_io_operations;
	u64 planned_io_bytes;
};

#define RH_REPLAY_SLOT_AUTHORITY_PROVIDER_VERSION 1U
#define RH_REPLAY_SLOT_AUTHORITY_SEAL_VERSION 1U

struct rh_replay_initialize_intent {
	u32 version;
	u64 volume_serial;
	u64 record_number;
	u64 physical_offset;
	u64 mft_vcn;
	s64 mft_lcn;
	u16 owner_sequence;
	u16 reserved16;
	u32 reserved32;
	unsigned char journal_uuid[16];
	unsigned char raw_before_hash[32];
	unsigned char redo_payload_hash[32];
};

struct rh_replay_slot_authority_seal {
	u32 version;
	u32 reserved32;
	u64 generation;
	u64 volume_serial;
	u64 record_number;
	u64 physical_offset;
	u64 mft_vcn;
	s64 mft_lcn;
	u16 owner_sequence;
	u16 reserved16;
	u32 reserved_flags;
	unsigned char journal_uuid[16];
	unsigned char raw_before_hash[32];
	unsigned char redo_payload_hash[32];
	unsigned char mft_bitmap_census_hash[32];
	unsigned char namespace_census_hash[32];
	unsigned char mft_extent_mapping_hash[32];
	u64 mft_slots_completed;
	u64 namespace_entries_examined;
	u8 identity_bound;
	u8 mft_bitmap_bit_clear;
	u8 namespace_census_complete;
	u8 slot_unreferenced;
	u8 extent_mapping_exact;
	u8 target_outside_wal;
	u8 target_outside_protected;
	u8 reserved8;
};

typedef int (*rh_replay_authorize_initialize_fn)(void *opaque,
		const struct rh_replay_initialize_intent *intent,
		struct rh_replay_slot_authority_seal *seal);

struct rh_replay_slot_authority_provider {
	u32 version;
	u32 reserved32;
	u64 expected_volume_serial;
	unsigned char expected_journal_uuid[16];
	rh_replay_authorize_initialize_fn authorize_initialize;
	void *opaque;
};

extern struct rh_writer *rh_replay_writer;
extern const struct rh_replay_slot_authority_provider
	*rh_replay_slot_authority_provider;
int roothealth_log_replay_plan(const char *device_name,
		struct rh_writer *writer, struct rh_log_result *result);
/*
 * Prove the normal boot fast path without walking historical log records.
 * A positive result requires a supported selected restart page marked clean,
 * a clear on-disk $Volume dirty flag, and no active Windows hibernation image.
 * Return 1 only for that complete proof, 0 when the full repair path must run,
 * and -1 for an invalid caller contract.
 */
int roothealth_boot_clean_probe(const char *device_name,
		struct rh_writer *writer, struct rh_log_result *result,
		int *dirty_out);
int roothealth_log_replay_plan_authorized(const char *device_name,
		struct rh_writer *writer,
		const struct rh_replay_slot_authority_provider *provider,
		struct rh_log_result *result);
/*
 * Re-derive a native plan from an already mounted immutable writer view.
 * Existing writer operations form the read-only base view; newly derived
 * operations are appended after checkpoint.
 */
int roothealth_log_replay_plan_mounted(ntfs_volume *volume,
		struct rh_writer *writer, size_t checkpoint,
		struct rh_log_result *result);
int roothealth_restart_page_supported(const RESTART_PAGE_HEADER *header,
		u64 expected_logfile_size);
LCN roothealth_attr_vcn_to_lcn(ntfs_attr *na, VCN vcn);
int roothealth_build_native_attr_target(ntfs_attr *na, VCN vcn, LCN lcn,
		u64 physical_offset, size_t length, enum rh_write_kind kind,
		struct rh_write_semantic_target *target);

extern RESTART_AREA restart;
extern LOG_CLIENT_RECORD client;

const char *actionname(int op);
const char *mftattrname(ATTR_TYPES attr);
void showname(const char *prefix, const char *name, int cnt);
int fixnamelen(const char *name, int len);
BOOL within_lcn_range(const LOG_RECORD *logr);
struct ATTR *getattrentry(unsigned int key, unsigned int lth);
struct ATTR *findattrentry(unsigned int key);
void copy_attribute(struct ATTR *pa, const char *buf, int length);
u32 get_undo_offset(const LOG_RECORD *logr);
u32 get_redo_offset(const LOG_RECORD *logr);
u32 get_extra_offset(const LOG_RECORD *logr);
BOOL exception(int num);

struct STORE;
extern int play_undos(ntfs_volume *vol, const struct ACTION_RECORD *firstundo);
extern int play_redos(ntfs_volume *vol, const struct ACTION_RECORD *firstredo);
extern void show_redos(void);
extern void freeclusterentry(struct STORE*);
void hexdump(const char *buf, unsigned int lth);

#endif
