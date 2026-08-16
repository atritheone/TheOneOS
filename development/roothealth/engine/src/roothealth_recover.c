/* ROOTHEALTH_IO_ROLE(PLANNER) */
/*
 *		Process log data from an NTFS partition
 *
 * Copyright (c) 2012-2017 Jean-Pierre Andre
 *
 *	This program examines the Windows log file of an ntfs partition
 *	and plays the committed transactions in order to restore the
 *	integrity of metadata.
 *
 *	It can also display the contents of the log file in human-readable
 *	text, either from a full partition or from the log file itself.
 *
 *
 *            History
 *
 *  Sep 2012
 *     - displayed textual logfile contents forward
 *
 *  Nov 2014
 *     - decoded multi-page log records
 *     - displayed textual logfile contents backward
 *
 *  Nov 2015
 *     - made a general cleaning and redesigned as an ntfsprogs
 *     - applied committed actions from logfile
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

#define BASEBLKS 4 /* number of special blocks (always shown) */
#define BASEBLKS2 34 /* number of special blocks when version >= 2.0 */
#define RSTBLKS 2 /* number of restart blocks */
#define BUFFERCNT 64 /* number of block buffers - a power of 2 */
#define NTFSBLKLTH 512 /* usa block size */
#define SHOWATTRS 20 /* max attrs shown in a dump */
#define SHOWLISTS 10 /* max lcn or lsn shown in a list */
#define BLOCKBITS 9 /* This is only used to read the restart page */
#define MAXEXCEPTION 10 /* Max number of exceptions (option -x) */
#define MINRECSIZE 48 /* Minimal log record size */
#define MAXRECSIZE 65536 /* Legacy display path; repair gate is stricter. */
#define ROOTHEALTH_MAX_ACTIONS RH_REPLAY_MAX_ACTIONS
#define ROOTHEALTH_MAX_LOGFILE_SIZE RH_REPLAY_MAX_LOGFILE_SIZE
#define ROOTHEALTH_NATIVE_WAL_MAX_OPERATIONS 4096U
#define ROOTHEALTH_NATIVE_WAL_MAX_TARGET_BYTES (100ULL * 1024ULL * 1024ULL)
#define ROOTHEALTH_REPLAY_PAGE_SIZE 4096U
#define ROOTHEALTH_V1_FIRST_PAGE BASEBLKS
#define ROOTHEALTH_V2_FIRST_PAGE BASEBLKS2

#include "config.h"

#ifdef HAVE_STDLIB_H
#include <stdlib.h>
#endif
#ifdef HAVE_STDIO_H
#include <stdio.h>
#endif
#ifdef HAVE_UNISTD_H
#include <unistd.h>
#endif
#ifdef HAVE_FCNTL_H
#include <fcntl.h>
#endif
#ifdef HAVE_ERRNO_H
#include <errno.h>
#endif
#ifdef HAVE_STRING_H
#include <string.h>
#endif
#ifdef HAVE_GETOPT_H
#include <getopt.h>
#endif
#ifdef HAVE_MALLOC_H
#include <malloc.h>
#endif
#ifdef HAVE_TIME_H
#include <time.h>
#endif

#include "types.h"
#include "endians.h"
#include "support.h"
#include "layout.h"
#include "param.h"
#include "ntfstime.h"
#include "device_io.h"
#include "device.h"
#include "logging.h"
#include "runlist.h"
#include "mft.h"
#include "inode.h"
#include "attrib.h"
#include "bitmap.h"
#include "index.h"
#include "volume.h"
#include "unistr.h"
#include "mst.h"
#include "logfile.h"
#include "roothealth_recover.h"
#include "roothealth_replay_guard.h"
#include "roothealth_replay_analysis.h"
#include "roothealth_write.h"
#include "utils.h"
#include "misc.h"

typedef struct {
	ntfs_volume *vol;
	FILE *file;
	struct ACTION_RECORD *firstaction;
	struct ACTION_RECORD *lastaction;
} CONTEXT;

typedef enum { T_OK, T_ERR, T_DONE } TRISTATE;

RESTART_PAGE_HEADER log_header;
RESTART_AREA restart;
LOG_CLIENT_RECORD client;
u32 clustersz = 0;
int clusterbits;
u32 blocksz;
int blockbits;
int log_major;
u16 bytespersect;
u64 mftlcn;
u32 mftrecsz;
int mftrecbits;
u32 mftcnt; /* number of entries */
ntfs_inode *log_ni;
ntfs_attr *log_na;
u64 logfilelcn;
u32 logfilesz; /* bytes */
u64 redos_met;
u64 committed_lsn;
u64 synced_lsn;
u64 latest_lsn;
u64 restart_lsn;
u64 offset_mask; /* block number in an lsn */
unsigned long firstblk; /* first block to dump (option -r) */
unsigned long lastblk;  /* last block to dump (option -r) */
u64 firstlcn; /* first block to dump (option -c) */
u64 lastlcn;  /* last block to dump (option -c) */
BOOL optb; /* show the log backward */
BOOL optc; /* restrict to cluster range */
BOOL optd; /* device argument present*/
BOOL opth; /* show help */
BOOL opti; /* show invalid (stale) records */
BOOL optf; /* show full log */
BOOL optk; /* kill fast restart */
BOOL optn; /* do not apply modifications */
BOOL optp; /* count of transaction sets to play */
BOOL optr; /* show a range of blocks */
int opts; /* sync the file system */
BOOL optt; /* show transactions */
BOOL optu; /* count of transaction sets to undo */
int optv; /* verbose */
int optV; /* version */
int optx[MAXEXCEPTION + 1];
struct ATTR **attrtable;
unsigned int actionnum;
unsigned int attrcount;
unsigned int playcount;
unsigned int playedactions; // change the name
unsigned int redocount;
unsigned int undocount;
struct BUFFER *buffer_table[BASEBLKS + BUFFERCNT];
unsigned int redirect[BASEBLKS2];
struct rh_writer *rh_replay_writer;
const struct rh_replay_slot_authority_provider
	*rh_replay_slot_authority_provider;
static unsigned int rh_restart_pages_planned;
static BOOL rh_log_needs_replay;
static unsigned char *rh_examined_pages;
static unsigned int rh_pages_expected;
static unsigned int rh_pages_examined;
static unsigned int rh_wiped_pages_scanned;
static unsigned int rh_unsupported_actions;
static unsigned int rh_io_errors;
static unsigned int rh_parse_errors;
static struct rh_replay_analysis_result rh_analysis_evidence;

static void roothealth_reset_log_evidence(void)
{
	free(rh_examined_pages);
	rh_examined_pages = NULL;
	rh_pages_expected = 0;
	rh_pages_examined = 0;
	rh_wiped_pages_scanned = 0;
	rh_unsupported_actions = 0;
	rh_io_errors = 0;
	rh_parse_errors = 0;
	memset(&rh_analysis_evidence, 0, sizeof(rh_analysis_evidence));
}

static int roothealth_prepare_log_evidence(void)
{
	if (logfilesz < RH_REPLAY_MIN_LOGFILE_SIZE ||
		logfilesz > RH_REPLAY_MAX_LOGFILE_SIZE ||
		(logfilesz & (RH_REPLAY_PAGE_SIZE - 1U)))
		return -1;
	rh_pages_expected = logfilesz / RH_REPLAY_PAGE_SIZE;
	rh_examined_pages = (unsigned char *)calloc(rh_pages_expected, 1);
	return rh_examined_pages ? 0 : -1;
}

static void roothealth_note_log_page(unsigned int page)
{
	if (!rh_examined_pages || page >= rh_pages_expected) {
		++rh_parse_errors;
		return;
	}
	if (!rh_examined_pages[page]) {
		rh_examined_pages[page] = 1;
		++rh_pages_examined;
	}
}

static int roothealth_replay_geometry(CONTEXT *ctx,
		struct rh_replay_geometry *geometry)
{
	if (!ctx || !ctx->vol || !geometry ||
		bytespersect != RH_REPLAY_SECTOR_SIZE)
		return -1;
	memset(geometry, 0, sizeof(*geometry));
	geometry->page_size = blocksz;
	geometry->cluster_size = clustersz;
	geometry->mft_record_size = mftrecsz;
	geometry->index_record_size = ctx->vol->indx_record_size;
	geometry->logfile_size = logfilesz;
	geometry->volume_clusters = ctx->vol->nr_clusters;
	geometry->sequence_bits = le32_to_cpu(restart.seq_number_bits);
	geometry->client_sequence = le16_to_cpu(client.seq_number);
	geometry->client_index = 0U;
	if (rh_replay_guard_profile(geometry)) {
		fprintf(stderr, "** Native replay geometry rejected"
			" page=%u cluster=%u mft=%u index=%u logfile=%llu"
			" clusters=%llu sequence=%u client=%u\n",
			geometry->page_size, geometry->cluster_size,
			geometry->mft_record_size, geometry->index_record_size,
			(unsigned long long)geometry->logfile_size,
			(unsigned long long)geometry->volume_clusters,
			geometry->sequence_bits, geometry->client_sequence);
		return -1;
	}
	return 0;
}

LCN roothealth_attr_vcn_to_lcn(ntfs_attr *na, VCN vcn)
{
	runlist_element *rl;
	VCN delta;

	rl = ntfs_attr_find_vcn(na, vcn);
	if (!rl)
		return LCN_EIO;
	if (rl->lcn < 0)
		return rl->lcn;
	delta = vcn - rl->vcn;
	if (delta < 0 || delta >= rl->length ||
			rl->lcn > INT64_MAX - delta) {
		errno = EIO;
		return LCN_EIO;
	}
	return rl->lcn + delta;
}

static const le16 SDS[4] = {
	const_cpu_to_le16('$'), const_cpu_to_le16('S'),
	const_cpu_to_le16('D'), const_cpu_to_le16('S')
} ;

static const le16 I30[4] = {
	const_cpu_to_le16('$'), const_cpu_to_le16('I'),
	const_cpu_to_le16('3'), const_cpu_to_le16('0')
} ;

/*
 *		Byte address of a log block
 */

static s64 loclogblk(CONTEXT *ctx, unsigned int blk)
{
	s64 loc;
	LCN lcn;

	if (ctx->vol) {
		lcn = roothealth_attr_vcn_to_lcn(log_na,
				((s64)blk << blockbits) >> clusterbits);
		loc = lcn << clusterbits;
	} else {
		if (((s64)blk << blockbits) >= logfilesz)
			loc = -1;
		else
			loc = (logfilelcn << clusterbits)
				+ ((s64)blk << blockbits);
	}
	return (loc);
}

static u64 roothealth_record_source_offset(const struct BUFFER *buffer,
		u16 within_page)
{
	u64 page_offset;

	if (!buffer || within_page >= blocksz)
		return UINT64_MAX;
	page_offset = (u64)buffer->num << blockbits;
	if (log_major < 2 && buffer->num >= RSTBLKS &&
			buffer->num < BASEBLKS)
		page_offset = (u64)sle64_to_cpu(buffer->block.record.copy.file_offset);
	if (page_offset >= logfilesz || page_offset > UINT64_MAX - within_page)
		return UINT64_MAX;
	return page_offset + within_page;
}

/*
 *		Deprotect a block
 *	Only to be used for log buffers
 *
 *	Returns 0 if block was found correct
 */

static int replaceusa(struct BUFFER *buffer, unsigned int lth)
{
	struct rh_replay_page_view view;
	u64 last_end;
	unsigned int i;
	unsigned int sector;
	u16 usn;

	if (buffer->num < RSTBLKS) {
		unsigned char *page = (unsigned char *)buffer->block.data;
		u16 usa_offset = getle16(page, 4);
		u16 area_offset = getle16(page, 24);

		if (lth != RH_REPLAY_PAGE_SIZE ||
			!((usa_offset == offsetof(RESTART_PAGE_HEADER, usn)) ||
			  (usa_offset == sizeof(RESTART_PAGE_HEADER))) ||
			getle16(page, 6) != 9U ||
			usa_offset + 18U > area_offset)
			return 1;
		usn = getle16(page, usa_offset);
		if (!usn)
			return 1;
		for (sector = 1; sector < 9U; ++sector) {
			size_t tail = (size_t)sector * RH_REPLAY_SECTOR_SIZE - 2U;
			size_t replacement = usa_offset + 2U * sector;

			if (getle16(page, tail) != usn)
				return 1;
			page[tail] = page[replacement];
			page[tail + 1U] = page[replacement + 1U];
		}
		return 0;
	}
	if (lth != RH_REPLAY_PAGE_SIZE) {
		fprintf(stderr, "** Invalid RCRD page size in logical block %u"
			" (physical block %u)\n", buffer->num, buffer->rnum);
		return 1;
	}
	for (i = 0; i < lth &&
		((unsigned char *)buffer->block.data)[i] == 0xffU; ++i)
		;
	if (i == lth)
		return 0;
	if (
		rh_replay_guard_unprotect_rcrd(
			(unsigned char *)buffer->block.data, lth, &view)) {
		fprintf(stderr, "** Invalid RCRD header or update sequence array"
			" in logical block %u (physical block %u)\n",
			buffer->num, buffer->rnum);
		return 1;
	}
	last_end = view.last_end_lsn;
	if (log_major >= 2) {
		u32 first_page = ROOTHEALTH_V2_FIRST_PAGE;
		u32 physical = buffer->rnum;
		u32 sequence_bits = le32_to_cpu(restart.seq_number_bits);
		u32 offset_bits;
		u64 mask;

		if (!sequence_bits || sequence_bits >= 64U || !view.copy_value ||
			((view.flags & 1U) && !last_end))
			return 1;
		offset_bits = 64U - sequence_bits;
		mask = (((u64)1) << offset_bits) - 1U;
		if (!(view.copy_value & ~mask) ||
			(view.copy_value & mask) >= logfilesz / 8U ||
			(last_end && (!(last_end & ~mask) ||
			(last_end & mask) >= logfilesz / 8U)))
			return 1;
		if (physical >= RSTBLKS && physical < ROOTHEALTH_V2_FIRST_PAGE) {
			if ((view.file_offset & (RH_REPLAY_PAGE_SIZE - 1U)) ||
				view.file_offset < first_page * RH_REPLAY_PAGE_SIZE ||
				view.file_offset >= logfilesz)
				return 1;
		} else if (physical >= ROOTHEALTH_V2_FIRST_PAGE &&
			view.file_offset) {
			return 1;
		}
	} else if (!last_end) {
		return 1;
	} else if (buffer->num < BASEBLKS) {
		u32 sequence_bits = le32_to_cpu(restart.seq_number_bits);
		u32 offset_bits;
		u64 mask;
		u64 record_page;

		if (!sequence_bits || sequence_bits >= 64U)
			return 1;
		offset_bits = 64U - sequence_bits;
		mask = offset_bits == 64U ? UINT64_MAX :
			((((u64)1) << offset_bits) - 1U);
		record_page = ((last_end & mask) << 3) &
			~((u64)RH_REPLAY_PAGE_SIZE - 1U);
		if ((view.copy_value & (RH_REPLAY_PAGE_SIZE - 1U)) ||
			view.copy_value < (u64)BASEBLKS * RH_REPLAY_PAGE_SIZE ||
			view.copy_value >= logfilesz || view.copy_value != record_page)
			return 1;
	} else {
		u32 sequence_bits = le32_to_cpu(restart.seq_number_bits);
		u32 offset_bits;
		u64 mask;
		u64 copy_page;
		u64 end_page;

		if (!sequence_bits || sequence_bits >= 64U ||
			view.copy_value < last_end ||
			view.copy_value - last_end > blocksz / 8U)
			return 1;
		offset_bits = 64U - sequence_bits;
		mask = offset_bits == 64U ? UINT64_MAX :
			((((u64)1) << offset_bits) - 1U);
		if (!(view.copy_value & ~mask) || !(last_end & ~mask) ||
			(view.copy_value & mask) >= logfilesz / 8U ||
			(last_end & mask) >= logfilesz / 8U)
			return 1;
		copy_page = ((view.copy_value & mask) << 3) >> blockbits;
		end_page = ((last_end & mask) << 3) >> blockbits;
		if (copy_page != buffer->rnum || end_page != buffer->rnum)
			return 1;
	}
	buffer->headsz = 0x40;
	return 0;
}

/*
 *		Dynamically allocate an attribute key.
 *
 *	As the possible values for a key depend on the version, we
 *	cannot convert it to an index, so we make dichotomical searches
 */

struct ATTR *getattrentry(unsigned int key, unsigned int lth)
{
	struct ATTR *pa;
	struct ATTR **grown;
	unsigned int low, mid, high;

	low = 0;
	high = attrcount;
	while (low < high) {
		mid = low + (high - low) / 2U;
		if (attrtable[mid]->key < key)
			low = mid + 1U;
		else
			high = mid;
	}
	mid = low;
	if ((mid < attrcount) && (attrtable[mid]->key == key)) {
		pa = attrtable[mid];
		if (pa->namelen < lth) {
			struct ATTR *resized = (struct ATTR*)realloc(pa,
					sizeof(struct ATTR) + lth);
			if (!resized)
				return NULL;
			pa = resized;
			attrtable[mid] = resized;
		}
	} else {
		pa = (struct ATTR*)malloc(sizeof(struct ATTR) + lth);
		if (pa) {
			grown = (struct ATTR**)realloc(attrtable,
				(attrcount + 1U) * sizeof(struct ATTR*));
			if (!grown) {
				free(pa);
				return NULL;
			}
			attrtable = grown;
			high = attrcount + 1U;
			while (--high > mid)
				attrtable[high] = attrtable[high - 1U];
			attrtable[mid] = pa;
			++attrcount;
		pa->key = key;
		pa->namelen = 0;
		pa->type = const_cpu_to_le32(0);
		pa->inode = 0;
		pa->reference = 0;
		pa->lsn = 0;
		pa->bytes_per_index = 0;
		}
	}
	return (pa);
}

struct ATTR *findattrentry(unsigned int key)
{
	unsigned int low = 0, high = attrcount;

	while (low < high) {
		unsigned int mid = low + (high - low) / 2U;
		if (attrtable[mid]->key < key)
			low = mid + 1U;
		else
			high = mid;
	}
	if (low < attrcount && attrtable[low]->key == key)
		return attrtable[low];
	return NULL;
}

/*
 *		Read blocks in a circular buffer
 *
 *	returns NULL if block cannot be read or it is found bad
 *		otherwise returns the full unprotected block data
 */

static const struct BUFFER *read_buffer(CONTEXT *ctx, unsigned int num)
{
	struct BUFFER *buffer;
	BOOL got;
	int k;
	unsigned int rnum;

		/*
		 * The first four blocks are stored apart, to make
		 * sure pages 2 and 3 and the page which is logically
		 * before them can be accessed at the same time.
		 * (Only two blocks are stored apart if version >= 2.0)
		 * Also, block 0 is smaller because it has to be read
		 * before the block size is known.
		 * Note : the last block is supposed to have an odd
		 * number, and cannot be overwritten by block 4 (or 34
		 * if version >= 2.0) which follows logically.
		 */
	if ((num < RSTBLKS)
	    || ((log_major < 2) && (num < BASEBLKS)))
		buffer = buffer_table[num + BUFFERCNT];
	else
		buffer = buffer_table[num & (BUFFERCNT - 1)];
	if (buffer && (buffer->size < blocksz)) {
		free(buffer);
		buffer = (struct BUFFER*)NULL;
	}
	if (!buffer) {
		buffer = (struct BUFFER*)
			malloc(sizeof(struct BUFFER) + blocksz);
		if (!buffer)
			return (const struct BUFFER*)NULL;
		buffer->size = blocksz;
		buffer->rnum = num + 1; /* forced to being read */
		buffer->safe = FALSE;
		if (num < BASEBLKS)
			buffer_table[num + BUFFERCNT] = buffer;
		else
			buffer_table[num & (BUFFERCNT - 1)] = buffer;
	}
	rnum = num;
	if (log_major >= 2) {
		for (k=RSTBLKS; k<BASEBLKS2; k++)
			if (redirect[k] == num)
				rnum = k;
	}
	if (buffer && (buffer->rnum != rnum)) {
		buffer->num = num;
		buffer->rnum = rnum;
		if (ctx->vol)
			got = (ntfs_attr_pread(log_na,(u64)rnum << blockbits,
				blocksz, buffer->block.data) == blocksz);
		else
			got = !fseek(ctx->file, loclogblk(ctx, rnum), 0)
			    && (fread(buffer->block.data, blocksz,
						1, ctx->file) == 1);
		if (got) {
			char *data = buffer->block.data;
			roothealth_note_log_page(rnum);
			buffer->headsz = 0;
			buffer->safe = !replaceusa(buffer, blocksz);
			if (!buffer->safe)
				++rh_parse_errors;
			if (buffer->safe && num < RSTBLKS) {
				unsigned int usa_count = getle16(data, 6);

				if (!usa_count || usa_count > 9U)
					buffer->safe = FALSE;
				else
					buffer->headsz = sizeof(RECORD_PAGE_HEADER)
						+ ((2U * usa_count - 1U) | 7U) + 1U;
			}
		} else {
			buffer->safe = FALSE;
			++rh_io_errors;
			fprintf(stderr,"** Could not read block %d\n", rnum);
		}
	}
	return (buffer && buffer->safe ? buffer : (const struct BUFFER*)NULL);
}

void hexdump(const char *buf, unsigned int lth)
{
	unsigned int i,j,k;

	for (i=0; i<lth; i+=16) {
		printf("%04x ",i);
		k = ((lth - i) < 16 ? lth : 16 + i);
		for (j=i; j<k; j++)
			printf((j & 3 ? "%02x" : " %02x"),buf[j] & 255);
		printf("%*c",(152 - 9*(j - i))/4,' ');
		for (j=i; j<k; j++)
			if ((buf[j] > 0x20) && (buf[j] < 0x7f))
				printf("%c",buf[j]);
			else
				printf(".");
		printf("\n");
	}
}

/*
 *	       Display a date
 */

static void showdate(const char *text, le64 lestamp)
{
	time_t utime;
	struct tm *ptm;
	s64 stamp;
	const char *months[]
		= { "Jan", "Feb", "Mar", "Apr", "May", "Jun",
		    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" } ;

	stamp = le64_to_cpu(lestamp);
	if ((stamp < ((2147000000 + 134774*86400LL)*10000000LL))
	    && (stamp > ((-2147000000 + 134774*86400LL)*10000000LL))) {
				/* date within traditional Unix limits */
		utime = stamp/10000000 - 134774*86400LL;
		ptm = gmtime(&utime);
		printf("%s %02d %3s %4d %2d:%02d:%02d UTC\n",
			text,
			ptm->tm_mday,months[ptm->tm_mon],ptm->tm_year+1900,
			ptm->tm_hour,ptm->tm_min,ptm->tm_sec);
	} else {
		u32 days;
		unsigned int year;
		int mon;
		int cnt;

		days = stamp/(86400*10000000LL);
		year = 1601;
					/* periods of 400 years */
		cnt = days/146097;
		days -= 146097*cnt;
		year += 400*cnt;
					/* periods of 100 years */
		cnt = (3*days + 3)/109573;
		days -= 36524*cnt;
		year += 100*cnt;
					/* periods of 4 years */
		cnt = days/1461;
		days -= 1461L*cnt;
		year += 4*cnt;
					/* periods of a single year */
		cnt = (3*days + 3)/1096;
		days -= 365*cnt;
		year += cnt;

		if ((!(year % 100) ? (year % 400) : (year % 4))
		    && (days > 58)) days++;
		if (days > 59) {
			mon = (5*days + 161)/153;
			days -= (153*mon - 162)/5;
		} else {
			mon = days/31 + 1;
			days -= 31*(mon - 1) - 1;
		}
if (mon > 12)
{
printf("** Bad day stamp %lld days %lu mon %d year %u\n",
(long long)stamp,(unsigned long)days,mon,year);
}
		printf("%s %02u %3s %4u\n",text,
			(unsigned int)days,months[mon-1],(unsigned int)year);
	}
}

void showname(const char *prefix, const char *name, int cnt)
{
	const le16 *n;
	int i;
	int c;

	printf("%s",prefix);
	n = (const le16*)name;
	for (i=0; (i<cnt) && n[i]; i++) {
		c = le16_to_cpu(n[i]);
		if (c < 0x20)
			printf(".");
		else
			if (c < 0x80)
				printf("%c",c);
			else
				if (c < 0x800)
					printf("%c%c",
						(c >> 6) + 0xc0,
						(c & 63) + 0x80);
				else
					printf("%c%c%c",
						(c >> 12) + 0xe0,
						((c >> 6) & 63) + 0x80,
						(c & 63) + 0x80);
	}
	printf("\n");
}

static const char *commitment(u64 lsn)
{
	const char *commit;
	s64 diff;

	/* Computations assume lsn could wraparound, they probably never do */
	diff = lsn - synced_lsn;
	if (diff <= 0)
		commit = "synced";
	else {
		diff = lsn - committed_lsn;
		if (diff <= 0)
			commit = "committed";
		else {
			/* may find lsn from older session */
			diff = lsn - latest_lsn;
			if (diff <= 0)
				commit = "*uncommitted*";
			else
				commit = "*stale*";
		}
	}
	return (commit);
}

const char *actionname(int op)
{
	static char buffer[24];
	const char *p;

	switch (op) {
	case Noop :
		p = "Noop";
		break;
	case CompensationlogRecord :
		p = "CompensationlogRecord";
		break;
	case InitializeFileRecordSegment :
		p = "InitializeFileRecordSegment";
		break;
	case DeallocateFileRecordSegment :
		p = "DeallocateFileRecordSegment";
		break;
	case WriteEndofFileRecordSegment :
		p = "WriteEndofFileRecordSegment";
		break;
	case CreateAttribute :
		p = "CreateAttribute";
		break;
	case DeleteAttribute :
		p = "DeleteAttribute";
		break;
	case UpdateResidentValue :
		p = "UpdateResidentValue";
		break;
	case UpdateNonResidentValue :
		p = "UpdateNonResidentValue";
		break;
	case UpdateMappingPairs :
		p = "UpdateMappingPairs";
		break;
	case DeleteDirtyClusters :
		p = "DeleteDirtyClusters";
		break;
	case SetNewAttributeSizes :
		p = "SetNewAttributeSizes";
		break;
	case AddIndexEntryRoot :
		p = "AddIndexEntryRoot";
		break;
	case DeleteIndexEntryRoot :
		p = "DeleteIndexEntryRoot";
		break;
	case AddIndexEntryAllocation :
		p = "AddIndexEntryAllocation";
		break;
	case DeleteIndexEntryAllocation :
		p = "DeleteIndexEntryAllocation";
		break;
	case WriteEndOfIndexBuffer :
		p = "WriteEndOfIndexBuffer";
		break;
	case SetIndexEntryVcnRoot :
		p = "SetIndexEntryVcnRoot";
		break;
	case SetIndexEntryVcnAllocation :
		p = "SetIndexEntryVcnAllocation";
		break;
	case UpdateFileNameRoot :
		p = "UpdateFileNameRoot";
		break;
	case UpdateFileNameAllocation :
		p = "UpdateFileNameAllocation";
		break;
	case SetBitsInNonResidentBitMap :
		p = "SetBitsInNonResidentBitMap";
		break;
	case ClearBitsInNonResidentBitMap :
		p = "ClearBitsInNonResidentBitMap";
		break;
	case HotFix :
		p = "HotFix";
		break;
	case EndTopLevelAction :
		p = "EndTopLevelAction";
		break;
	case PrepareTransaction :
		p = "PrepareTransaction";
		break;
	case CommitTransaction :
		p = "CommitTransaction";
		break;
	case ForgetTransaction :
		p = "ForgetTransaction";
		break;
	case OpenNonResidentAttribute :
		p = "OpenNonResidentAttribute";
		break;
	case OpenAttributeTableDump :
		p = "OpenAttributeTableDump";
		break;
	case AttributeNamesDump :
		p = "AttributeNamesDump";
		break;
	case DirtyPageTableDump :
		p = "DirtyPageTableDump";
		break;
	case TransactionTableDump :
		p = "TransactionTableDump";
		break;
	case UpdateRecordDataRoot :
		p = "UpdateRecordDataRoot";
		break;
	case UpdateRecordDataAllocation :
		p = "UpdateRecordDataAllocation";
		break;
	case UpdateRelativeDataInIndex :
		p = "UpdateRelativeDataInIndex";
		break;
	case UpdateRelativeDataInIndex2 :
		p = "UpdateRelativeDataInIndex2";
		break;
	case ZeroEndOfFileRecord :
		p = "ZeroEndOfFileRecord";
		break;
	default  :
		sprintf(buffer,"*Unknown-Action-%d*",op);
		p = buffer;
		break;
	}
	return (p);
}

static const char *attrname(unsigned int key)
{
	static char name[256];
	const char *p;
	struct ATTR *pa;
	unsigned int i;

	if ((key <= 65535) && !(key & 3)) {
		pa = getattrentry(key,0);
		if (pa) {
			if (!pa->namelen)
				p = "Unnamed";
			else {
				p = name;
					/* Assume ascii for now */
				for (i=0; 2*i<pa->namelen; i++)
					name[i] = le16_to_cpu(pa->name[i]);
				name[i] = 0;
			}
		} else
			p = "Undefined";
	} else
		p = "Invalid";
	return (p);
}

int fixnamelen(const char *name, int len)
{
	int i;

	i = 0;
	while ((i < len) && (name[i] || name[i + 1]))
		i += 2;
	return (i);
}

const char *mftattrname(ATTR_TYPES attr)
{
	static char badattr[24];
	const char *p;

	switch (attr) {
	case AT_STANDARD_INFORMATION :
		p = "Standard-Information";
		break;
	case AT_ATTRIBUTE_LIST :
		p = "Attribute-List";
		break;
	case AT_FILE_NAME :
		p = "Name";
		break;
	case AT_OBJECT_ID :
		p = "Volume-Version";
		break;
	case AT_SECURITY_DESCRIPTOR :
		p = "Security-Descriptor";
		break;
	case AT_VOLUME_NAME :
		p = "Volume-Name";
		break;
	case AT_VOLUME_INFORMATION :
		p = "Volume-Information";
		break;
	case AT_DATA :
		p = "Data";
		break;
	case AT_INDEX_ROOT :
		p = "Index-Root";
		break;
	case AT_INDEX_ALLOCATION :
		p = "Index-Allocation";
		break;
	case AT_BITMAP :
		p = "Bitmap";
		break;
	case AT_REPARSE_POINT :
		p = "Reparse-Point";
		break;
	case AT_EA_INFORMATION :
		p = "EA-Information";
		break;
	case AT_EA :
		p = "EA";
		break;
	case AT_PROPERTY_SET :
		p = "Property-Set";
		break;
	case AT_LOGGED_UTILITY_STREAM :
		p = "Logged-Utility-Stream";
		break;
	case AT_END :
		p = "End";
		break;
	default :
		sprintf(badattr,"*0x%x-Unknown*",attr);
		p = badattr;
		break;
	}
	return (p);
}

static void showattribute(const char *prefix, const struct ATTR *pa)
{
	if (pa) {
		if (pa->type) {
			printf("%sattr 0x%x : inode %lld type %s",
				prefix, pa->key, (long long)pa->inode,
				mftattrname(pa->type));
			if (pa->namelen)
				showname(" name ",(const char*)pa->name,
					pa->namelen/2);
			else
				printf("\n");
		} else {
			if (pa->namelen) {
				printf("%sattr 0x%x : type Unknown",
						prefix, pa->key);
				showname(" name ",(const char*)pa->name,
						pa->namelen/2);
			} else
				printf("%s(definition of attr 0x%x not met)\n",
						prefix, pa->key);
		}
	}
}

/*
 *		Determine if an action acts on the MFT
 */

static BOOL acts_on_mft(int op)
{
	BOOL onmft;

			/* A few actions may have to be added to the list */
	switch (op) {
	case InitializeFileRecordSegment :
	case DeallocateFileRecordSegment :
	case CreateAttribute :
	case DeleteAttribute :
	case UpdateResidentValue :
	case UpdateMappingPairs :
	case SetNewAttributeSizes :
	case AddIndexEntryRoot :
	case DeleteIndexEntryRoot :
	case UpdateFileNameRoot :
	case UpdateRelativeDataInIndex :
	case WriteEndofFileRecordSegment :
	case ZeroEndOfFileRecord :
		onmft = TRUE;
		break;
	default :
		onmft = FALSE;
		break;
	}
	return (onmft);
}

static BOOL roothealth_windows_control_layout(const LOG_RECORD *logr)
{
	u16 op = le16_to_cpu(logr->redo_operation);

	return !logr->lcns_to_follow && op >= OpenAttributeTableDump &&
		op <= DirtyPageTableDump &&
		le16_to_cpu(logr->target_attribute) == 24U &&
		le16_to_cpu(logr->attribute_flags) == 2U;
}

u32 get_undo_offset(const LOG_RECORD *logr)
{
	u32 offset;

	if (logr->lcns_to_follow || roothealth_windows_control_layout(logr))
		offset = 0x30 + le16_to_cpu(logr->undo_offset);
	else
		offset = 0x28 + le16_to_cpu(logr->undo_offset);
	return (offset);
}

u32 get_redo_offset(const LOG_RECORD *logr)
{
	u32 offset;

	if (logr->lcns_to_follow || roothealth_windows_control_layout(logr))
		offset = 0x30 + le16_to_cpu(logr->redo_offset);
	else
		offset = 0x28 + le16_to_cpu(logr->redo_offset);
	return (offset);
}

u32 get_extra_offset(const LOG_RECORD *logr)
{
	u32 uoffset;
	u32 roffset;

	roffset = get_redo_offset(logr)
				+ le16_to_cpu(logr->redo_length);
	uoffset = get_undo_offset(logr)
				+ le16_to_cpu(logr->undo_length);
	return ((((uoffset > roffset ? uoffset : roffset) - 1) | 7) + 1);
}

static BOOL likelyop(const LOG_RECORD *logr, size_t available)
{
	BOOL likely;
	u32 client_length;
	size_t record_size;

	if (!logr || available < LOG_RECORD_HEAD_SZ)
		return FALSE;
	client_length = le32_to_cpu(logr->client_data_length);
	if (client_length > RH_REPLAY_MAX_ACTION_SIZE - LOG_RECORD_HEAD_SZ)
		return FALSE;
	record_size = (size_t)client_length + LOG_RECORD_HEAD_SZ;
	if (record_size < sizeof(LOG_RECORD) ||
		record_size > available || record_size > RH_REPLAY_MAX_ACTION_SIZE)
		return FALSE;

	switch (logr->record_type) {
	case LOG_STANDARD : /* standard record */
	     /* Operations in range 0..LastAction-1, can be both null */
		likely = ((unsigned int)le16_to_cpu(logr->redo_operation)
						< LastAction)
		    && ((unsigned int)le16_to_cpu(logr->undo_operation)
						< LastAction)
	     /* Offsets aligned to 8 bytes */
		    && !(le16_to_cpu(logr->redo_offset) & 7)
		    && !(le16_to_cpu(logr->undo_offset) & 7)
	     /* transaction id must not be null */
		    && logr->transaction_id
	     /* client data length aligned to 8 bytes */
		    && !(le32_to_cpu(logr->client_data_length) & 7)
	     /* client data length less than 64K (131K ?) */
		    && (le32_to_cpu(logr->client_data_length) < MAXRECSIZE)
	     /* if there is redo data, offset must be >= 0x28 */
		    && (!le16_to_cpu(logr->redo_length)
		       || ((unsigned int)le16_to_cpu(logr->redo_offset) >= 0x28))
	     /* if there is undo data, offset must be >= 0x28 */
		    && (!le16_to_cpu(logr->undo_length)
		       || ((unsigned int)le16_to_cpu(logr->undo_offset) >= 0x28));
	     /* undo data and redo data should be contiguous when both present */
		if (likely && logr->redo_length && logr->undo_length) {
	     /* undo and redo data may be the same when both present and same size */
			if (logr->undo_offset == logr->redo_offset) {
				if (logr->redo_length != logr->undo_length)
					likely = FALSE;
			} else {
				if (le16_to_cpu(logr->redo_offset)
					< le16_to_cpu(logr->undo_offset)) {
			/* undo expected just after redo */
					if ((((le16_to_cpu(logr->redo_offset)
					    + le16_to_cpu(logr->redo_length)
					    - 1) | 7) + 1)
					    != le16_to_cpu(logr->undo_offset))
						likely = FALSE;
				} else {
			/* redo expected just after undo */
					if ((((le16_to_cpu(logr->undo_offset)
					    + le16_to_cpu(logr->undo_length)
					    - 1) | 7) + 1)
					    != le16_to_cpu(logr->redo_offset))
						likely = FALSE;
				}
			}
		}
		break;
	case LOG_CHECKPOINT : /* check-point */
	     /*
	      * undo and redo operations are null
	      * or CompensationlogRecord with no data
	      */
		likely = (!logr->redo_operation
			|| ((logr->redo_operation == const_cpu_to_le16(1))
			    && !logr->redo_length))
		    && (!logr->undo_operation
			|| ((logr->undo_operation == const_cpu_to_le16(1))
			    && !logr->undo_length))
	     /* transaction id must be null */
		    && !logr->transaction_id
	     /* client_data_length is 0x68 or 0x70 (Vista and subsequent) */
		    && ((le32_to_cpu(logr->client_data_length) == 0x68)
			|| (le32_to_cpu(logr->client_data_length) == 0x70));
		break;
	default :
		likely = FALSE;
		break;
	}
	return (likely);
}

/*
 *		Search for a likely record in a block
 *
 *	Must not be used when syncing.
 *
 *	Returns 0 when not found
 */

static u16 searchlikely(const struct BUFFER *buf)
{
	const LOG_RECORD *logr;
	const char *data;
	u16 k;

	if (opts)
		printf("** Error : searchlikely() used for syncing\n");
        data = buf->block.data;
	k = buf->headsz;
	logr = (const LOG_RECORD*)&data[k];
	if (!likelyop(logr, blocksz - k)) {
		do {
			k += 8;
			logr = (const LOG_RECORD*)&data[k];
		} while ((k <= (blocksz - LOG_RECORD_HEAD_SZ))
		    && !likelyop(logr, blocksz - k));
		if (k > (blocksz - LOG_RECORD_HEAD_SZ))
			k = 0;
	}
	return (k);
}

/*
 *	From a previous block, determine the location of first record
 *
 *	The previous block must have the beginning of an overlapping
 *	record, and the current block must have the beginning of next
 *	record (which can overlap on next blocks).
 *	The argument "skipped" is the number of blocks in-between.
 *
 *	Note : the overlapping record from previous block does not reach
 *	the current block when it ends near the end of the last skipped block.
 *
 *	Returns 0 if some bad condition is found
 *	Returns near blocksz when there is no beginning of record in
 *		the current block
 */

static u16 firstrecord(int skipped, const struct BUFFER *buf,
		   const struct BUFFER *prevbuf)
{
	const RECORD_PAGE_HEADER *rph;
	const RECORD_PAGE_HEADER *prevrph;
	const LOG_RECORD *logr;
	const char *data;
	const char *prevdata;
	u16 k;
	u16 blkheadsz;
	s32 size;

	rph = &buf->block.record;
	data = buf->block.data;
	if (prevbuf) {
		prevrph = &prevbuf->block.record;
		prevdata = prevbuf->block.data;
		blkheadsz = prevbuf->headsz;
		/* From previous page, determine where the current one starts */
		k = le16_to_cpu(prevrph->next_record_offset);
		/* a null value means there is no full record in next block */
		if (!k)
			k = blkheadsz;
	} else
		k = 0;
		/* Minimal size is apparently 48 : offset of redo_operation */
	if (k && ((blocksz - k) >= LOG_RECORD_HEAD_SZ)) {
		logr = (const LOG_RECORD*)&prevdata[k];
		if (!logr->client_data_length) {
			/*
			 * Sometimes the end of record is free space.
			 * This apparently means reaching the end of
			 * a previous session, and must be considered
			 * as an error.
			 * We however tolerate this, unless syncing
			 * is requested.
			 */
			printf("* Reaching free space at end of block %d\n",
					(int)prevbuf->num);
			/* As a consequence, there cannot be skipped blocks */
			if (skipped) {
				printf("*** Inconsistency : blocks skipped after free space\n");
				k = 0; /* error returned */
			}
			if (opts)
				k = 0;
			else {
				k = searchlikely(buf);
				printf("* Skipping over free space\n");
			}
		} else {
			size = le32_to_cpu(logr->client_data_length)
					+ LOG_RECORD_HEAD_SZ;
			if ((size < MINRECSIZE) || (size > MAXRECSIZE)) {
				printf("** Bad record size %ld in block %ld"
					" offset 0x%x\n",
					(long)size,(long)prevbuf->num,(int)k);
				k = blkheadsz;
			} else {
				if ((int)(blocksz - k) >= size)
					printf("*** Inconsistency : the final"
						" record does not overlap\n");
				k += size - (blocksz - blkheadsz)*(skipped + 1);
			}
			if ((k <= blkheadsz)
			    && (k > (blkheadsz - LOG_RECORD_HEAD_SZ))) {
			/* There were not enough space in the last skipped block */
				k = blkheadsz;
			} else {
				if (optv
				    && ((blocksz - k) < LOG_RECORD_HEAD_SZ)) {
					/* Not an error : just no space */
					printf("No minimal record space\n");
				}
				if (optv >= 2)
					printf("Overlapping record from block %d,"
						" starting at offset 0x%x\n",
						(int)prevbuf->num,(int)k);
			}
		}
	} else {
		k = buf->headsz;
		if (optv >= 2) {
			if (prevbuf)
				printf("No minimal record from block %d,"
					" starting at offset 0x%x\n",
					(int)prevbuf->num, (int)k);
			else
				printf("No block before %d,"
					" starting at offset 0x%x\n",
					(int)buf->num, (int)k);
		}
	}
		/*
		 * In a wraparound situation, there is frequently no
		 * match... because there were no wraparound.
		 * Return an error if syncing is requested, otherwise
		 * try to find a starting record.
		 */
	if (k && prevbuf && (prevbuf->num > buf->num)) {
		logr = (const LOG_RECORD*)&data[k];
			/* Accept reaching the end with no record beginning */
		if ((k != le16_to_cpu(rph->next_record_offset))
		    && !likelyop(logr, blocksz - k)) {
			if (opts) {
				k = 0;
				printf("** Could not wraparound\n");
			} else {
				k = searchlikely(buf);
				printf("* Skipping over bad wraparound\n");
			}
		}
	}
	return (k);
}

/*
 *		Find the block which defines the first record in current one
 *
 *	Either the wanted block has the beginning of a record overlapping
 *	on current one, or it ends in such as there is no space for an
 *	overlapping one.
 *
 *	Returns 0 if the previous block cannot be determined.
 */

static const struct BUFFER *findprevious(CONTEXT *ctx, const struct BUFFER *buf)
{
	const struct BUFFER *prevbuf;
	const struct BUFFER *savebuf;
	const RECORD_PAGE_HEADER *rph;
	int skipped;
	int prevblk;
	BOOL prevmiddle;
	BOOL error;
	u16 endoff;

	error = FALSE;
	prevblk = buf->num;
	savebuf = (struct BUFFER*)NULL;
	skipped = 0;
	do {
		prevmiddle = FALSE;
		if (prevblk > (log_major < 2 ? BASEBLKS : BASEBLKS2))
			prevblk--;
		else
			if (prevblk == (log_major < 2 ? BASEBLKS : BASEBLKS2))
				prevblk = (logfilesz >> blockbits) - 1;
			else {
				rph = &buf->block.record;
				if (log_major < 2)
					prevblk = (sle64_to_cpu(
						rph->copy.file_offset)
							>> blockbits) - 1;
				else
					prevblk = (sle64_to_cpu(
						rph->copy.last_lsn)
						    & offset_mask)
							>> (blockbits - 3);
				/*
				 * If an initial block leads to block 4, it
				 * can mean the last block or no previous
				 * block at all. Using the last block is safer,
				 * its lsn will indicate whether it is stale.
				 */
				if (prevblk
				    < (log_major < 2 ? BASEBLKS : BASEBLKS2))
					prevblk = (logfilesz >> blockbits) - 1;
			}
		/* No previous block if the log only consists of block 2 or 3 */
		if (prevblk < BASEBLKS) {
			prevbuf = (struct BUFFER*)NULL;
			error = TRUE; /* not a real error */
		} else {
			prevbuf = read_buffer(ctx, prevblk);
			if (prevbuf) {
				rph = &prevbuf->block.record;
				prevmiddle = !(rph->flags
						& const_cpu_to_le32(1))
					|| !rph->next_record_offset;
				if (prevmiddle) {
					savebuf = prevbuf;
					skipped++;
				}
			} else {
				error = TRUE;
				printf("** Could not read block %d\n",
								(int)prevblk);
			}
		}
	} while (prevmiddle && !error);

	if (!prevmiddle && !error && skipped) {
	 /* No luck if there is not enough space in this record */
		rph = &prevbuf->block.record;
		endoff = le16_to_cpu(rph->next_record_offset);
		if (endoff > (blocksz - LOG_RECORD_HEAD_SZ)) {
			prevbuf = savebuf;
		}
	}
	return (error ? (struct BUFFER*)NULL : prevbuf);
}

void copy_attribute(struct ATTR *pa, const char *buf, int length)
{
	const ATTR_NEW *panew;
	ATTR_OLD old_aligned;

	if (pa) {
		switch (length) {
		case sizeof(ATTR_NEW) :
			panew = (const ATTR_NEW*)buf;
			pa->type = panew->type;
			pa->lsn = sle64_to_cpu(panew->lsn);
			pa->reference = le64_to_cpu(panew->inode);
			pa->inode = MREF(pa->reference);
			break;
		case sizeof(ATTR_OLD) :
				/* Badly aligned, first realign */
			memcpy(&old_aligned,buf,sizeof(old_aligned));
			pa->type = old_aligned.type;
			pa->lsn = sle64_to_cpu(old_aligned.lsn);
			pa->reference = le64_to_cpu(old_aligned.inode);
			pa->inode = MREF(pa->reference);
			break;
		default :
			printf("** Unexpected attribute format, length %d\n",
					length);
		}
	}
}

static void roothealth_clear_attributes(void)
{
	unsigned int i;

	for (i = 0; i < attrcount; ++i)
		free(attrtable[i]);
	free(attrtable);
	attrtable = NULL;
	attrcount = 0;
}

static int roothealth_load_open_attribute(struct ATTR *pa,
		const unsigned char *entry, size_t length)
{
	u32 type;
	u64 inode;
	u64 lsn;

	if (!pa || !entry)
		return -1;
	if (length == 40U) {
		type = getle32((const char *)entry, 8);
		inode = getle64((const char *)entry, 16);
		lsn = getle64((const char *)entry, 24);
	} else if (length == 44U) {
		inode = getle64((const char *)entry, 8);
		lsn = getle64((const char *)entry, 16);
		type = getle32((const char *)entry, 28);
	} else {
		return -1;
	}
	if (!type || (type & 0xfU) || type > 0x100U || !inode)
		return -1;
	pa->type = cpu_to_le32(type);
	pa->inode = MREF(inode);
	pa->reference = inode;
	pa->lsn = lsn;
	pa->bytes_per_index = length == 40U ?
		getle32((const char *)entry, 4) :
		getle32((const char *)entry, 40);
	return 0;
}

static int roothealth_refresh_open_table(const unsigned char *table,
		size_t length)
{
	u16 step, slots, allocated;
	unsigned int allocated_seen = 0;
	u16 slot;

	if (!table || length < 24U)
		return -1;
	step = getle16((const char *)table, 0);
	slots = getle16((const char *)table, 2);
	allocated = getle16((const char *)table, 4);
	if ((step != 40U && step != 44U) || !slots || allocated > slots ||
		(size_t)step * slots != length - 24U)
		return -1;
	for (slot = 0; slot < slots; ++slot) {
		const unsigned char *entry = table + 24U + (size_t)slot * step;
		u32 key = 24U + (u32)slot * step;
		struct ATTR *pa;

		if (getle32((const char *)entry, 0) != UINT32_MAX)
			continue;
		if (key > UINT16_MAX)
			return -1;
		pa = getattrentry(key, 0);
		if (!pa || roothealth_load_open_attribute(pa, entry, step))
			return -1;
		++allocated_seen;
	}
	return allocated_seen == allocated ? 0 : -1;
}

static int roothealth_refresh_attribute_names(const unsigned char *names,
		size_t length)
{
	size_t offset = 0;

	while (offset + 4U <= length) {
		u16 key = getle16((const char *)names, (int)offset);
		u16 bytes = getle16((const char *)names, (int)offset + 2);
		struct ATTR *pa;

		if (!key) {
			offset += 4U;
			while (offset < length)
				if (names[offset++])
					return -1;
			return 0;
		}
		if ((bytes & 1U) || bytes > 510U ||
			bytes > length - offset - 4U || !findattrentry(key))
			return -1;
		pa = getattrentry(key, bytes);
		if (!pa)
			return -1;
		pa->namelen = bytes;
		memcpy(pa->name, names + offset + 4U, bytes);
		offset += 4U + bytes;
	}
	return -1;
}

static int refresh_attributes(const struct ACTION_RECORD *firstaction)
{
	const struct ACTION_RECORD *action;
	int saw_table = 0;

	roothealth_clear_attributes();
	for (action = firstaction; action; action = action->next) {
		const LOG_RECORD *logr = &action->record;
		u16 op;
		u32 record_size = le32_to_cpu(logr->client_data_length) +
			LOG_RECORD_HEAD_SZ;
		u32 redo_at = get_redo_offset(logr);
		u32 undo_at = get_undo_offset(logr);
		u16 redo_length = le16_to_cpu(logr->redo_length);
		u16 undo_length = le16_to_cpu(logr->undo_length);
		const unsigned char *bytes = (const unsigned char *)logr;
		struct ATTR *pa;

		if (logr->record_type == LOG_CHECKPOINT)
			continue;
		op = le16_to_cpu(logr->redo_operation);
		if (record_size < 88U || redo_at > record_size ||
			redo_length > record_size - redo_at || undo_at > record_size ||
			undo_length > record_size - undo_at)
			goto fail;
		switch (op) {
		case OpenNonResidentAttribute: {
			u16 key = le16_to_cpu(logr->target_attribute);
			if ((redo_length != 40U && redo_length != 44U) ||
				(undo_length & 1U) || undo_length > 510U ||
				findattrentry(key))
				goto fail;
			pa = getattrentry(key, undo_length);
			if (!pa || roothealth_load_open_attribute(pa,
					bytes + redo_at, redo_length))
				goto fail;
			pa->namelen = undo_length;
			if (undo_length)
				memcpy(pa->name, bytes + undo_at, undo_length);
			break;
		}
		case OpenAttributeTableDump:
			if (saw_table || roothealth_refresh_open_table(bytes + redo_at,
					redo_length))
				goto fail;
			saw_table = 1;
			break;
		case AttributeNamesDump:
			if (redo_length) {
				if (!roothealth_windows_control_layout(logr) ||
					roothealth_refresh_attribute_names(bytes + redo_at,
						redo_length))
					goto fail;
			} else if (record_size < 80U ||
				roothealth_refresh_attribute_names(bytes + 80U,
					record_size - 80U))
				goto fail;
			break;
		default:
			break;
		}
	}
	return 0;
fail:
	roothealth_clear_attributes();
	return -1;
}

/*
 *              Display a fixup
 */

static void fixup(CONTEXT *ctx, const LOG_RECORD *logr, const char *buf,
				BOOL redo)
{
	struct ATTR *pa;
	int action;
	int attr;
	int offs;
	s32 length;
	int extra;
	s32 i;
	int p;
	s32 base;
	u16 firstpos; /* position of first mft attribute */
	le32 v;
	ATTR_TYPES mftattr;
	le64 w;
	le64 inode;
	le64 size;
	int lth;
	int len;

	attr = le16_to_cpu(logr->target_attribute);
	offs = le16_to_cpu(logr->attribute_offset);
	if (redo) {
		action = le16_to_cpu(logr->redo_operation);
		length = le16_to_cpu(logr->redo_length);
	} else {
		action = le16_to_cpu(logr->undo_operation);
		length = le16_to_cpu(logr->undo_length);
	}
	if (redo)
		printf("redo fixup %dR %s attr 0x%x offs 0x%x\n",
			actionnum, actionname(action), attr, offs);
	else
		printf("undo fixup %dU %s attr 0x%x offs 0x%x\n",
			actionnum, actionname(action), attr, offs);
	switch (action) {
	case InitializeFileRecordSegment : /* 2 */
			/*
			 * When this is a redo (with a NoOp undo), the
			 *   full MFT record is logged.
			 * When this is an undo (with DeallocateFileRecordSegment redo),
			 *   only the header of the MFT record is logged.
			 */
		if (!ctx->vol && !mftrecsz && (length > 8)) {
			/* mftrecsz can be determined from usa_count */
			mftrecsz = (getle16(buf,6) - 1)*512;
			mftrecbits = 1;
			while ((u32)(1 << mftrecbits) < mftrecsz)
				mftrecbits++;
		}
		printf("   new base MFT record, attr 0x%x (%s)\n",attr,attrname(attr));
		printf("   inode      %lld\n",
				(((long long)sle64_to_cpu(logr->target_vcn)
					<< clusterbits)
				+ (le16_to_cpu(logr->cluster_index) << 9))
					>> mftrecbits);
		if (length >= 18)
			printf("   seq number 0x%04x\n",(int)getle16(buf, 16));
		if (length >= 20)
			printf("   link count %d\n",(int)getle16(buf, 18));
		if (length >= 24) {
			u16 flags;

			flags = getle16(buf, 22);
			printf("   flags      0x%x",(int)flags);
			switch (flags & 3) {
			case 1 :
				printf(" (file in use)\n");
				break;
			case 3 :
				printf(" (directory in use)\n");
				break;
			default :
				printf(" (not in use)\n");
				break;
			}
		}
		base = getle16(buf, 4) + ((getle16(buf, 6)*2 - 1) | 7) + 1;
		while (base < length) {
			mftattr = feedle32(buf, base);
			printf("   attrib 0x%lx (%s) at offset 0x%x\n",
				(long)le32_to_cpu(mftattr),
				mftattrname(mftattr), (int)base);
		if (mftattr == AT_FILE_NAME) {
			showname("      name ",&buf[base + 90],
					buf[base + 88] & 255);
			inode = feedle64(buf, base + 24);
			printf("      parent dir inode %lld\n",
					(long long)MREF(le64_to_cpu(inode)));
		}
		lth =  getle32(buf, base + 4);
		if ((lth <= 0) || (lth & 7))
			base = length;
		else
			base += lth;
		}
		break;
	case DeallocateFileRecordSegment : /* 3 */
		printf("   free base MFT record, attr 0x%x (%s)\n",
				attr,attrname(attr));
		printf("   inode %lld\n",
		    (((long long)sle64_to_cpu(logr->target_vcn) << clusterbits)
		    + (le16_to_cpu(logr->cluster_index) << 9)) >> mftrecbits);
		break;
	case CreateAttribute : /* 5 */
		pa = getattrentry(attr,0);
		base = 24;
		/* Assume the beginning of the attribute is always present */
		switch (getle32(buf,0)) {
		case 0x30 :
			printf("   create file name, attr 0x%x\n",attr);
			if (pa)
				showattribute("      ",pa);
			showname("   file ",
				&buf[base + 66],buf[base + 64] & 255);
			if (base >= -8)
				showdate("   created  ",feedle64(buf,base + 8));
			if (base >= -16)
				showdate("   modified ",feedle64(buf,base + 16));
			if (base >= -24)
				showdate("   changed  ",feedle64(buf,base + 24));
			if (base >= -32)
				showdate("   read     ",feedle64(buf,base + 32));
			size = feedle64(buf,base + 40);
			printf("   allocated size %lld\n",
					(long long)le64_to_cpu(size));
			size = feedle64(buf,base + 48);
			printf("   real size %lld\n",
					(long long)le64_to_cpu(size));
			v = feedle32(buf,base + 56);
			printf("   DOS flags 0x%lx\n",
					(long)le32_to_cpu(v));
			break;
		case 0x80 :
			printf("   create a data stream, attr 0x%x\n",attr);
			break;
		case 0xc0 :
			printf("   create reparse data\n");
			if (pa)
				showattribute("      ",pa);
			printf("   tag 0x%lx\n",(long)getle32(buf, base));
			showname("   print name ",
				&buf[base + 20 + getle16(buf, base + 12)],
				getle16(buf, base + 14)/2);
			break;
		}
		break;
      case UpdateResidentValue : /* 7 */
		/*
		 * The record offset designates the mft attribute offset,
		 * offs and length define a right-justified window in this
		 * attribute.
		 * At this stage, we do not know which kind of mft
		 * attribute this is about, we assume this is standard
		 * information when it is the first attribute in the
		 * record.
		 */
		base = 0x18 - offs; /* p 8 */
		pa = getattrentry(attr,0);
		firstpos = 0x30 + (((mftrecsz/512 + 1)*2 - 1 ) | 7) + 1;
		if (pa
		   && !pa->inode
		   && (pa->type == const_cpu_to_le32(0x80))
		   && !(offs & 3)
		   && (le16_to_cpu(logr->record_offset) == firstpos)) {
			printf("   set standard information, attr 0x%x\n",attr);
			showattribute("      ",pa);
			if ((base >= 0) && ((base + 8) <= length))
				showdate("   created  ",
						feedle64(buf,base));
			if (((base + 8) >= 0) && ((base + 16) <= length))
				showdate("   modified ",
						feedle64(buf,base + 8));
			if (((base + 16) >= 0) && ((base + 24) <= length))
				showdate("   changed  ",
						feedle64(buf,base + 16));
			if (((base + 24) >= 0) && ((base + 32) <= length))
				showdate("   read     ",
						feedle64(buf,base + 24));
			if (((base + 32) >= 0) && ((base + 36) <= length)) {
				v = feedle32(buf, base + 32);
				printf("   DOS flags 0x%lx\n",
						(long)le32_to_cpu(v));
			}
			if (((base + 52) >= 0) && ((base + 56) <= length)) {
				v = feedle32(buf, base + 52);
				printf("   security id 0x%lx\n",
						(long)le32_to_cpu(v));
			}
			if (((base + 64) >= 0) && ((base + 72) <= length)) {
				/*
				 * This is badly aligned for Sparc when
				 * stamps not present and base == 52
				 */
				memcpy(&w, &buf[base + 64], 8);
				printf("   journal idx 0x%llx\n",
						(long long)le64_to_cpu(w));
			}
		} else {
			printf("   set an MFT attribute at offset 0x%x, attr 0x%x\n",
					(int)offs, attr);
			if (pa)
				showattribute("      ",pa);
		}
		break;
	case UpdateNonResidentValue : /* 8 */
		printf("   set attr 0x%x (%s)\n",attr,attrname(attr));
		pa = getattrentry(attr,0);
		if (pa)
			showattribute("      ",pa);
		base = 0; /* ? */
// Should not be decoded, unless attr is of identified type (I30, ...)
		if (pa && (pa->namelen == 8) && !memcmp(pa->name, SDS, 8)) {
			if (length >= 4)
				printf("   security hash 0x%lx\n",
						(long)getle32(buf, 0));
			if (length >= 8)
				printf("   security id 0x%lx\n",
						(long)getle32(buf, 4));
			if (length >= 20)
				printf("   entry size  %ld\n",
						(long)getle32(buf, 16));
		}
		if (pa && (pa->namelen == 8) && !memcmp(pa->name, I30, 8)) {
			if (!memcmp(buf, "INDX", 4))
				base = 64; /* full record */
			else
				base = 0;  /* entries */
			inode = feedle64(buf, base);
			printf("   inode  %lld\n",
			     (long long)MREF(le64_to_cpu(inode)));
			inode = feedle64(buf, base + 16);
			printf("   parent inode %lld\n",
			     (long long)MREF(le64_to_cpu(inode)));
			showname("   file    ",&buf[base + 82],
							buf[base + 80] & 255);
			showdate("   date    ",feedle64(buf, base + 32));
		}
		break;
	case UpdateMappingPairs : /* 9 */
		printf("   update runlist in attr 0x%x (%s)\n",attr,
				attrname(attr));
	       /* argument is a compressed runlist (or part of it ?) */
	       /* stop when finding 00 */
		break;
	case SetNewAttributeSizes : /* 11 */
		printf("   set sizes in attr 0x%x (%s)\n",attr,attrname(attr));
		base = 0; /* left justified ? */
		size = feedle64(buf,0);
		printf("     allocated size %lld\n",(long long)le64_to_cpu(size));
		size = feedle64(buf,8);
		printf("          real size %lld\n",(long long)le64_to_cpu(size));
		size = feedle64(buf,16);
		printf("   initialized size %lld\n",(long long)le64_to_cpu(size));
		break;
	case AddIndexEntryRoot : /* 12 */
	case AddIndexEntryAllocation : /* 14 */
		/*
		 * The record offset designates the mft attribute offset,
		 * offs and length define a left-justified window in this
		 * attribute.
		 */
		if (action == AddIndexEntryRoot)
			printf("   add resident index entry, attr 0x%x\n",attr);
		else
			printf("   add nonres index entry, attr 0x%x\n",attr);
		pa = getattrentry(attr,0);
		if (pa)
			showattribute("      ",pa);
		base = 0;
		p = getle16(buf, base + 8);
		/* index types may be discriminated by inode in base+0 */
		switch (p) { /* size of index entry */
		case 32 :  /* $R entry */
			memcpy(&inode, &buf[base + 20], 8); /* bad align */
			printf("   $R reparse index\n");
			printf("   reparsed inode 0x%016llx\n",
					(long long)le64_to_cpu(inode));
			printf("   reparse tag 0x%lx\n",
					(long)getle32(buf, 16));
			break;
		case 40 :  /* $SII entry */
			printf("   $SII security id index\n");
			printf("   security id 0x%lx\n",
					(long)getle32(buf, 16));
			printf("   security hash 0x%lx\n",
					(long)getle32(buf, 20));
			break;
		case 48 :  /* $SDH entry */
			printf("   $SDH security id index\n");
			printf("   security id 0x%lx\n",
					(long)getle32(buf, 20));
			printf("   security hash 0x%lx\n",
					(long)getle32(buf, 16));
			break;
		default :
		  /* directory index are at least 84 bytes long, ntfsdoc p 98 */
		  /* have everything needed to create the index */
			lth = buf[base + 80] & 255;
		  /* consistency of file name length */
			if (getle16(buf,10) == (u32)(2*lth + 66)) {
				printf("   directory index\n");
				inode = feedle64(buf,16);
				printf("   parent dir inode %lld\n",
					(long long)MREF(le64_to_cpu(inode)));
				if (feedle32(buf,72)
						& const_cpu_to_le32(0x10000000))
					showname("   file (dir) ",
						&buf[base + 82],
						buf[base + 80] & 255);
				else
					showname("   file ",
						&buf[base + 82],
						buf[base + 80] & 255);
				inode = feedle64(buf,0);
				printf("   file inode %lld\n",
					(long long)MREF(le64_to_cpu(inode)));
				size = feedle64(buf,64);
				printf("   file size %lld\n",
					(long long)le64_to_cpu(size));
				showdate("   created  ",
						feedle64(buf,base + 24));
				showdate("   modified ",
						feedle64(buf,base + 32));
				showdate("   changed  ",
						feedle64(buf,base + 40));
				showdate("   read     ",
						feedle64(buf,base + 48));
			} else
				printf("   unknown index type\n");
			break;
			}
		break;
	case SetIndexEntryVcnRoot : /* 17 */
		printf("   set vcn of non-resident index root, attr 0x%x\n",
				attr);
		pa = getattrentry(attr,0);
		if (pa)
			showattribute("      ",pa);
		printf("   vcn %lld\n", (long long)getle64(buf,0));
		break;
	case UpdateFileNameRoot : /* 19 */
		/*
		 * Update an entry in a resident directory index.
		 * The record offset designates the mft attribute offset,
		 * offs and length define a right-justified window in this
		 * attribute.
		 */
		printf("   set directory resident entry, attr 0x%x\n",attr);
		base = length - 0x50;
		pa = getattrentry(attr,0);
		if (pa)
			showattribute("      ",pa);
		if (pa
		   && !pa->inode
		   && (pa->type == const_cpu_to_le32(0x80))
		   && !(offs & 3)) {
			if (base >= -24)
				showdate("   created  ",feedle64(buf,
							base + 24));
			if (base >= -32)
				showdate("   modified ",feedle64(buf,
							base + 32));
			if (base >= -40)
				showdate("   changed  ",feedle64(buf,
							base + 40));
			if (base >= -48)
				showdate("   read     ",feedle64(buf,
							base + 48));
			if (base >= -56) {
				size = feedle64(buf,base + 56);
				printf("   allocated size %lld\n",
						(long long)le64_to_cpu(size));
			}
			if (base >= -64) {
				size = feedle64(buf,base + 64);
				printf("   real size %lld\n",
						(long long)le64_to_cpu(size));
			}
			if (base > -72) {
				v = feedle32(buf,base + 72);
				printf("   DOS flags 0x%lx\n",
						(long)le32_to_cpu(v));
			}
		} else {
			/* Usually caused by attr not yet defined */
			if (pa && pa->type)
				printf("** Unexpected index parameters\n");
		}
		break;
	case UpdateFileNameAllocation : /* 20 */
		     /* update entry in directory index */
		     /* only dates, sizes and attrib */
		base = length - 64; /* p 12 */
		printf("   set directory nonres entry, attr 0x%x\n",attr);
		pa = getattrentry(attr,0);
		if (pa)
			showattribute("      ",pa);
		if (base >= -8)
			showdate("   created  ",feedle64(buf, base + 8));
		if (base >= -16)
			showdate("   modified ",feedle64(buf, base + 16));
		if (base >= -24)
			showdate("   changed  ",feedle64(buf, base + 24));
		if (base >= -32)
			showdate("   read     ",*(const le64*)&buf[base + 32]);
		if (base >= -40) {
			size = feedle64(buf, base + 40);
			printf("   allocated size %lld\n",
						(long long)le64_to_cpu(size));
		}
		if (base >= -48) {
			size = feedle64(buf, base + 48);
			printf("   real size %lld\n",
						(long long)le64_to_cpu(size));
		}
		if (base >= -56) {
			v = feedle32(buf, base + 56);
			printf("   DOS flags 0x%lx\n",(long)le32_to_cpu(v));
		}
		break;
	case SetBitsInNonResidentBitMap : /* 21 */
	case ClearBitsInNonResidentBitMap : /* 22 */
		if (action == SetBitsInNonResidentBitMap)
			printf("   SetBitsInNonResidentBitMap, attr 0x%x\n",
					attr);
		else
			printf("   ClearBitsInNonResidentBitMap, attr 0x%x\n",
					attr);
		pa = getattrentry(attr,0);
		if (pa)
			showattribute("      ",pa);
		v = feedle32(buf, 0);
		printf("   first bit %ld\n",(long)le32_to_cpu(v));
		v = feedle32(buf, 4);
		printf("   bit count %ld\n",(long)le32_to_cpu(v));
		break;
	case OpenNonResidentAttribute : /* 28 */
		printf("   OpenNonResidentAttribute, attr 0x%x\n",attr);
		extra = get_extra_offset(logr)
			- (redo ? get_redo_offset(logr)
				: get_undo_offset(logr));
		if (logr->undo_length) {
			len = le32_to_cpu(logr->client_data_length)
				+ LOG_RECORD_HEAD_SZ
				- get_extra_offset(logr);
			/* this gives a length aligned modulo 8 */
			len = fixnamelen(&buf[extra], len);
		} else
			len = 0;
		pa = getattrentry(attr,len);
		if (pa && redo) {
			/*
			 * If this is a redo, collect the attribute data.
			 * This should only be done when walking forward.
			 */
			copy_attribute(pa, buf, length);
			pa->namelen = len;
			if (len)
				memcpy(pa->name,&buf[extra],len);
			printf("   MFT attribute 0x%lx (%s)\n",
				(long)le32_to_cpu(pa->type),
				mftattrname(pa->type));
			printf("   lsn   0x%016llx\n",
				(long long)pa->lsn);
			printf("   inode %lld\n",
				(long long)pa->inode);
		}
		if (logr->undo_length)
			showname("   extra : attr name ", &buf[extra], len/2);
		if (!redo && length) {
			printf("   * undo attr not shown\n");
		}
		break;
	case OpenAttributeTableDump : /* 29 */
		printf("   OpenAttributeTableDump, attr 0x%x (%s)\n",
				attr,attrname(attr));
		i = 24;
		if (i < length) {
			int x;
			int more;
			int step;
			int used;

			step = getle16(buf, 8);
			used = getle16(buf, 12);
			    /*
			     * Changed from Win10, formerly we got step = 44.
			     * The record layout has also changed
			     */
			if ((step != sizeof(ATTR_OLD))
			    && (step != sizeof(ATTR_NEW))) {
				printf("   ** Unexpected step %d\n",step);
			}
			more = 0;
			for (x=0; (x<used) && (i<length); i+=step, x++) {
				pa = getattrentry(i,0);
				if (pa) {
					copy_attribute(pa, &buf[i], step);
					if (x <= SHOWATTRS) {
						printf("   attr 0x%x inode %lld"
							" type %s",
							(int)i,
							(long long)pa->inode,
							mftattrname(pa->type));
						if (pa->namelen)
							showname(" name ",
								(char*)pa->name,
								pa->namelen/2);
						else
							printf("\n");
					} else
						more++;
				}
			}
			if (more)
				printf("   (%d more attrs not shown)\n",more);
		}
		break;
	case AttributeNamesDump : /* 30 */
		printf("   AttributeNamesDump, attr 0x%x (%s)\n",
			       attr,attrname(attr));
		i = 8;
		if (i < length) {
			unsigned int l;
			unsigned int key;
			int x;
			int more;

			more = 0;
			x = 0;
			do {
				l = le16_to_cpu(*(const le16*)&buf[i+2]);
				key = le16_to_cpu(*(const le16*)&buf[i]);
				if (l > 510) {
					printf("** Error : bad attribute name"
							" length %d\n",l);
					key = 0;
				}
		 /* Apparently, may have to stop before reaching the end */
				if (key) {
					pa = getattrentry(key,l);
					if (pa) {
						pa->namelen = l;
						memcpy(pa->name,&buf[i+4],l);
					}
					if (x < SHOWATTRS) {
						printf("   attr 0x%x is",key);
						showname("  ",&buf[i+4],l/2);
					} else
						more++;
					i += l + 6;
					x++;
				}
			} while (key && (i < length));
			if (more)
				printf("   (%d more attrs not shown)\n",more);
		}
		break;
	default :
		break;
	}
}

static void detaillogr(CONTEXT *ctx, const LOG_RECORD *logr)
{
	u64 lcn;
	u64 baselcn;
	unsigned int i;
	unsigned int off;
	unsigned int undo;
	unsigned int redo;
	unsigned int extra;
	unsigned int end;
	unsigned int listsize;
	BOOL onmft;

	switch (logr->record_type) {
	case LOG_STANDARD :
		onmft = logr->cluster_index
			|| acts_on_mft(le16_to_cpu(logr->redo_operation))
			|| acts_on_mft(le16_to_cpu(logr->undo_operation));
		printf("redo_operation         %04x %s\n",
			(int)le16_to_cpu(logr->redo_operation),
			actionname(le16_to_cpu(logr->redo_operation)));
		printf("undo_operation         %04x %s\n",
			(int)le16_to_cpu(logr->undo_operation),
			actionname(le16_to_cpu(logr->undo_operation)));
		printf("redo_offset            %04x\n",
			(int)le16_to_cpu(logr->redo_offset));
		printf("redo_length            %04x\n",
			(int)le16_to_cpu(logr->redo_length));
		printf("undo_offset            %04x\n",
			(int)le16_to_cpu(logr->undo_offset));
		printf("undo_length            %04x\n",
			(int)le16_to_cpu(logr->undo_length));
		printf("target_attribute       %04x\n",
			(int)le16_to_cpu(logr->target_attribute));
		printf("lcns_to_follow         %04x\n",
			(int)le16_to_cpu(logr->lcns_to_follow));
		printf("record_offset          %04x\n",
			(int)le16_to_cpu(logr->record_offset));
		printf("attribute_offset       %04x\n",
			(int)le16_to_cpu(logr->attribute_offset));
		printf("cluster_index          %04x\n",
			(int)le16_to_cpu(logr->cluster_index));
		printf("attribute_flags        %04x\n",
			(int)le16_to_cpu(logr->attribute_flags));
		if (mftrecbits && onmft)
			printf("target_vcn             %016llx (inode %lld)\n",
				(long long)sle64_to_cpu(logr->target_vcn),
				(((long long)sle64_to_cpu(logr->target_vcn)
					<< clusterbits)
				+ (le16_to_cpu(logr->cluster_index) << 9))
					 >> mftrecbits);
		else
			printf("target_vcn             %016llx\n",
				(long long)sle64_to_cpu(logr->target_vcn));
			/* Compute a base for the current run of mft */
		baselcn = sle64_to_cpu(logr->lcn_list[0])
					- sle64_to_cpu(logr->target_vcn);
		for (i=0; i<le16_to_cpu(logr->lcns_to_follow)
						&& (i<SHOWLISTS); i++) {
			lcn = sle64_to_cpu(logr->lcn_list[i]);
			printf("  (%d offs 0x%x) lcn    %016llx",i,
				(int)(8*i + sizeof(LOG_RECORD) - 8),
				(long long)lcn);
			lcn &= 0xffffffffffffULL;
			if (mftrecsz && onmft) {
				if (clustersz > mftrecsz)
					printf(" (MFT records for inodes"
						" %lld-%lld)\n",
						(long long)((lcn - baselcn)
							*clustersz/mftrecsz),
						(long long)((lcn + 1 - baselcn)
							*clustersz/mftrecsz - 1));
				else
					printf(" (MFT record for inode %lld)\n",
						(long long)((lcn - baselcn)
							*clustersz/mftrecsz));
				printf("     assuming record for inode %lld\n",
					(long long)((lcn - baselcn)
						*clustersz/mftrecsz
					+ (le16_to_cpu(logr->cluster_index)
						 >> 1)));
			} else
				printf("\n");
		}
                /*
                 *  redo_offset and undo_offset are considered unsafe
		 *  (actually they are safe when you know the logic)
                 *  2) redo : redo (defined by redo_offset)
                 *  3) undo : undo (defined by undo_offset)
                 *  4) extra : unknown data (end of undo to data_length)
                 */
         end = le32_to_cpu(logr->client_data_length) + LOG_RECORD_HEAD_SZ;
         if (logr->redo_length && logr->undo_length)
            {
                          /* both undo and redo are present */
            if (le16_to_cpu(logr->undo_offset) <=
						le16_to_cpu(logr->redo_offset))
               {
               undo = sizeof(LOG_RECORD) - 8
					+ 8*le16_to_cpu(logr->lcns_to_follow);
               if (logr->redo_offset == logr->undo_offset)
                  redo = undo;
               else
                  redo = undo + ((le16_to_cpu(logr->undo_length) - 1) | 7) + 1;
               extra = redo + ((le16_to_cpu(logr->redo_length) - 1) | 7) + 1;
               }
            else
               {
               redo = sizeof(LOG_RECORD) - 8
					+ 8*le16_to_cpu(logr->lcns_to_follow);
               undo = redo + ((le16_to_cpu(logr->redo_length) - 1) | 7) + 1;
               extra = undo + ((le16_to_cpu(logr->undo_length) - 1) | 7) + 1;
               }
            }
         else
            if (logr->redo_length)
               {
                                  /* redo and not undo */
               redo = undo = sizeof(LOG_RECORD) - 8
					+ 8*le16_to_cpu(logr->lcns_to_follow);
               extra = redo + ((le16_to_cpu(logr->redo_length) - 1) | 7) + 1;
               }
            else
               {
                                  /* optional undo and not redo */
               redo = undo = sizeof(LOG_RECORD) - 8
					+ 8*le16_to_cpu(logr->lcns_to_follow);
               extra = undo + ((le16_to_cpu(logr->undo_length) - 1) | 7) + 1;
               }

         printf("redo 0x%x (%u) undo 0x%x (%u) extra 0x%x (%d)\n",
                  redo,(int)(((le16_to_cpu(logr->redo_length) - 1) | 7) + 1),
                  undo,(int)(((le16_to_cpu(logr->undo_length) - 1) | 7) + 1),
                  extra,(int)(end > extra ? end - extra : 0));

	if (logr->redo_length && (get_redo_offset(logr) != redo))
		printf("** Unexpected redo offset 0x%x %u (%u)\n",
			get_redo_offset(logr),(int)redo,
			(int)le16_to_cpu(logr->lcns_to_follow));
	if (logr->undo_length && (get_undo_offset(logr) != undo))
		printf("** Unexpected undo offset 0x%x %u (%u)\n",
			get_undo_offset(logr),(int)undo,
			(int)le16_to_cpu(logr->lcns_to_follow));
	if (get_extra_offset(logr) != extra)
		printf("** Unexpected extra offset 0x%x %u (%u)\n",
			get_extra_offset(logr),(int)extra,
			(int)le16_to_cpu(logr->lcns_to_follow));

         if (extra <= end)
            {
                                       /* show redo data */
            if (logr->redo_length)
               {
               if (logr->lcns_to_follow)
                  {
                  off = le16_to_cpu(logr->record_offset)
					+ le16_to_cpu(logr->attribute_offset);
                  printf("redo data (new data) cluster 0x%llx pos 0x%x :\n",
                        (long long)sle64_to_cpu(logr->lcn_list[off
						>> clusterbits]),
                        (int)(off & (clustersz - 1)));
                  }
               else
			printf("redo data (new data) at offs 0x%x :\n",redo);
               if ((u32)(redo + le16_to_cpu(logr->redo_length))
                    <= end)
                  {
                  hexdump((const char*)logr
				+ redo,le16_to_cpu(logr->redo_length));
                  fixup(ctx, logr, (const char*)logr + redo, TRUE);
                  }
               else printf("redo data overflowing from record\n");
               }
            else
               {
               printf("no redo data (new data)\n");
               fixup(ctx, logr, (const char*)logr + redo, TRUE);
               }

                                     /* show undo data */
            if (logr->undo_length)
               {
               if (logr->lcns_to_follow)
                   {
                   off = le16_to_cpu(logr->record_offset)
					+ le16_to_cpu(logr->attribute_offset);
                   printf("undo data (old data) cluster 0x%llx pos 0x%x :\n",
                         (long long)sle64_to_cpu(logr->lcn_list[off
							>> clusterbits]),
                         (int)(off & (clustersz - 1)));
                   }
               else printf("undo data (old data) at offs 0x%x :\n",undo);
               if ((u32)(undo + le16_to_cpu(logr->undo_length)) <= end)
                  {
                  if ((undo + le16_to_cpu(logr->undo_length)) < 2*blocksz)
                     {
                     hexdump((const char*)logr
					+ undo,le16_to_cpu(logr->undo_length));
                     fixup(ctx, logr, (const char*)logr + undo, FALSE);
                     }
                  else printf("undo data overflowing from two blocks\n");
                  }
               else printf("undo data overflowing from record\n");
               }
            else
               {
               printf("no undo data (old data)\n");
               fixup(ctx, logr, (const char*)logr + undo, FALSE);
               }

                                    /* show extra data, if any */
            if (extra != end)
               {
               if (end > blocksz)
                  printf("invalid extra data size\n");
               else
                  {
                  printf("extra data at offs 0x%x\n",extra);
                  hexdump((const char*)logr + extra,
                            end - extra);
                  }
               }
            }
         else
            {
			/* sometimes the designated data overflows */
            if (logr->redo_length
              && ((u32)(redo + le16_to_cpu(logr->redo_length)) > end))
                printf("* redo data overflows from record\n");
            if (logr->undo_length
              && ((u32)(undo + le16_to_cpu(logr->undo_length)) > end))
                printf("* undo data overflows from record\n");
	    }
		break;
	case LOG_CHECKPOINT :
		printf("---> checkpoint record\n");
		printf("redo_operation         %04x %s\n",
			(int)le16_to_cpu(logr->redo_operation),
			actionname(le16_to_cpu(logr->redo_operation)));
		printf("undo_operation         %04x %s\n",
			(int)le16_to_cpu(logr->undo_operation),
			actionname(le16_to_cpu(logr->undo_operation)));
		printf("redo_offset            %04x\n",
			(int)le16_to_cpu(logr->redo_offset));
		printf("redo_length            %04x\n",
			(int)le16_to_cpu(logr->redo_length));
		printf("transaction_lsn        %016llx\n",
			(long long)sle64_to_cpu(logr->transaction_lsn));
		printf("attributes_lsn         %016llx\n",
			(long long)sle64_to_cpu(logr->attributes_lsn));
		printf("names_lsn              %016llx\n",
			(long long)sle64_to_cpu(logr->names_lsn));
		printf("dirty_pages_lsn        %016llx\n",
			(long long)sle64_to_cpu(logr->dirty_pages_lsn));
		listsize = le32_to_cpu(logr->client_data_length)
				+ LOG_RECORD_HEAD_SZ
				- offsetof(LOG_RECORD, unknown_list);
		if (listsize > 8*SHOWLISTS)
			listsize = 8*SHOWLISTS;
		for (i=0; 8*i<listsize; i++)
			printf("unknown-%u              %016llx\n",i,
				(long long)le64_to_cpu(logr->unknown_list[i]));
		break;
	default :
		printf("** Unknown action type\n");
		if (le32_to_cpu(logr->client_data_length) < blocksz) {
			printf("client_data for record type %ld\n",
				(long)le32_to_cpu(logr->record_type));
			hexdump((const char*)&logr->redo_operation,
				le32_to_cpu(logr->client_data_length));
		} else
			printf("** Bad client data\n");
		break;
	}
}

BOOL within_lcn_range(const LOG_RECORD *logr)
{
	u64 lcn;
	unsigned int i;
	BOOL within;

	within = FALSE;
	switch (logr->record_type) {
	case LOG_STANDARD :
		for (i=0; i<le16_to_cpu(logr->lcns_to_follow); i++) {
			lcn = MREF(sle64_to_cpu(logr->lcn_list[i]));
			if ((lcn >= firstlcn) && (lcn <= lastlcn))
				within = TRUE;
		}
		break;
	default :
		break;
	}
	return (within);
}

static void showlogr(CONTEXT *ctx, int k, const LOG_RECORD *logr)
{
	s32 diff;

	if (optv && (!optc || within_lcn_range(logr))) {
		diff = sle64_to_cpu(logr->this_lsn) - synced_lsn;
		printf("this_lsn               %016llx (synced%s%ld) %s\n",
			(long long)sle64_to_cpu(logr->this_lsn),
			(diff < 0 ? "" : "+"),(long)diff,
			commitment(diff + synced_lsn));
		printf("client_previous_lsn    %016llx\n",
			(long long)sle64_to_cpu(logr->client_previous_lsn));
		printf("client_undo_next_lsn   %016llx\n",
			(long long)sle64_to_cpu(logr->client_undo_next_lsn));
		printf("client_data_length     %08lx\n",
			(long)le32_to_cpu(logr->client_data_length));
		printf("seq_number             %d\n",
			(int)le16_to_cpu(logr->client_id.seq_number));
		printf("client_index           %d\n",
			(int)le16_to_cpu(logr->client_id.client_index));
		printf("record_type            %08lx\n",
			(long)le32_to_cpu(logr->record_type));
		printf("transaction_id         %08lx\n",
			(long)le32_to_cpu(logr->transaction_id));
		printf("log_record_flags       %04x\n",
			(int)le16_to_cpu(logr->log_record_flags));
		printf("reserved1              %04x %04x %04x\n",
			(int)le16_to_cpu(logr->reserved_or_alignment[0]),
		(int)le16_to_cpu(logr->reserved_or_alignment[1]),
		(int)le16_to_cpu(logr->reserved_or_alignment[2]));
		detaillogr(ctx, logr);
	}
	if (optt) {
		const char *state;

		if (logr->record_type == LOG_CHECKPOINT)
			state = "--checkpoint--";
		else
			state = commitment(sle64_to_cpu(logr->this_lsn));
		printf("      at %04x  %016llx %s (%ld) %s\n",k,
			(long long)sle64_to_cpu(logr->this_lsn),
			state,
			(long)(sle64_to_cpu(logr->this_lsn) - synced_lsn),
			actionname(le16_to_cpu(logr->redo_operation)));
		if (logr->client_previous_lsn || logr->client_undo_next_lsn) {
			if (logr->client_previous_lsn
					== logr->client_undo_next_lsn) {
				printf("                               "
					" previous and undo %016llx\n",
					(long long)sle64_to_cpu(
						logr->client_previous_lsn));
			} else {
				printf("                               "
					" previous %016llx",
					(long long)sle64_to_cpu(
						logr->client_previous_lsn));

				if (logr->client_undo_next_lsn)
					printf(" undo %016llx\n",
						(long long)sle64_to_cpu(
						logr->client_undo_next_lsn));
				else
					printf("\n");
			}
		}
	}
}

static int roothealth_analyze_transactions(CONTEXT *ctx,
		struct ACTION_RECORD *firstaction)
{
	struct rh_replay_analysis_record *records;
	struct rh_replay_analysis_result analysis;
	struct rh_replay_geometry geometry;
	struct ACTION_RECORD *action;
	unsigned int action_count = 0;
	unsigned int i = 0;
	int err;

	for (action = firstaction; action; action = action->next)
		if (++action_count > RH_REPLAY_MAX_ACTIONS)
			return 1;
	if (!action_count || !ctx || roothealth_replay_geometry(ctx, &geometry))
		return 1;
	records = (struct rh_replay_analysis_record *)calloc(action_count,
		sizeof(*records));
	if (!records)
		return 1;
	for (action = firstaction; action; action = action->next) {
		records[i].bytes = (const unsigned char *)&action->record;
		records[i].size = (size_t)le32_to_cpu(
			action->record.client_data_length) + LOG_RECORD_HEAD_SZ;
		++i;
	}
	err = rh_replay_analysis_plan(records, action_count, &geometry,
		synced_lsn, latest_lsn, &analysis);
	if (!err) {
		rh_analysis_evidence = analysis;
		i = 0;
		for (action = firstaction; action; action = action->next) {
			action->flags &= ~(ACTION_TO_REDO | ACTION_TO_UNDO);
			if (records[i].plan_flags & RH_REPLAY_PLAN_REDO)
				action->flags |= ACTION_TO_REDO;
			if (records[i].plan_flags & RH_REPLAY_PLAN_UNDO)
				action->flags |= ACTION_TO_UNDO;
			if (records[i].has_effective_lcn) {
				if (!action->record.lcns_to_follow) {
					err = 1;
					break;
				}
				action->record.lcn_list[0] =
					cpu_to_sle64(records[i].effective_lcn);
			}
			++i;
		}
	}
	free(records);
	return err;
}

/*
 *		Enqueue an action and play the queued actions on end of set
 */

static int roothealth_guard_log_record(CONTEXT *ctx, const LOG_RECORD *logr,
		int size, u64 source_byte_offset,
		struct rh_replay_action_view *view)
{
	struct rh_replay_geometry geometry;

	if (size < 0 || source_byte_offset >= logfilesz ||
		(source_byte_offset >> blockbits) <
			(log_major < 2 ? ROOTHEALTH_V1_FIRST_PAGE :
			 ROOTHEALTH_V2_FIRST_PAGE) ||
		(source_byte_offset & (blocksz - 1U)) < 0x40U ||
		roothealth_replay_geometry(ctx, &geometry))
		return -1;
	if (rh_replay_guard_action((const unsigned char *)logr, (size_t)size,
			&geometry, source_byte_offset, view)) {
		if (size >= (int)sizeof(LOG_RECORD)) {
			u16 operation = le16_to_cpu(logr->redo_operation);

			if (operation >= LastAction)
				++rh_unsupported_actions;
			else
				++rh_parse_errors;
		} else
			++rh_parse_errors;
		fprintf(stderr, "** Native action preflight rejected LSN 0x%llx"
			" at byte offset 0x%llx\n",
			(long long)sle64_to_cpu(logr->this_lsn),
			(long long)source_byte_offset);
		return -1;
	}
	return 0;
}

static TRISTATE enqueue_action(CONTEXT *ctx, const LOG_RECORD *logr,
				int size, int num, u64 source_byte_offset)
{
	struct ACTION_RECORD *action;
	struct rh_replay_action_view guarded;
	TRISTATE state;
	int err;

	err = 1;
	state = T_ERR;
	if (num <= 0 || (unsigned int)num > ROOTHEALTH_MAX_ACTIONS ||
			size < (int)sizeof(LOG_RECORD) ||
			size > (int)RH_REPLAY_MAX_ACTION_SIZE ||
			roothealth_guard_log_record(ctx, logr, size,
				source_byte_offset, &guarded)) {
		printf("** Refusing an unbounded or malformed log action\n");
		return T_ERR;
	}
		/* enqueue record */
	action = (struct ACTION_RECORD*)
			malloc(size + offsetof(struct ACTION_RECORD, record));
	if (action) {
		memcpy(&action->record, logr, size);
		action->num = num;
		action->flags = 0;
		/* enqueue ahead of list, firstaction is the oldest one */
		action->prev = (struct ACTION_RECORD*)NULL;
		action->next = ctx->firstaction;
		if (ctx->firstaction)
			ctx->firstaction->prev = action;
		else
			ctx->lastaction = action;
		ctx->firstaction = action;
		err = 0;
		state = T_OK;
		if ((optp || optu)
		    && (logr->record_type == LOG_CHECKPOINT)) {
			/* if chkp process queue, and increment count */
			playedactions++;
			if (playedactions <= playcount) {
				if (optv)
					printf("* Refreshing attributes\n");
				err = refresh_attributes(ctx->firstaction);
				if (optv)
					printf("* Undoing transaction set %d"
						" (actions %d->%d)\n",
						(int)playedactions,
						(int)ctx->lastaction->num,
						(int)ctx->firstaction->num);
				err = play_undos(ctx->vol, ctx->lastaction);
				if (err)
					printf("* Undoing transaction"
							" set failed\n");
			}
			if (!err && optp && (playedactions == playcount)) {
				if (optv)
					printf("* Redoing transaction set %d"
						" (actions %d->%d)\n",
						(int)playedactions,
						(int)ctx->firstaction->num,
						(int)ctx->lastaction->num);
				err = roothealth_analyze_transactions(ctx,
					ctx->firstaction);
				if (!err)
					err = play_redos(ctx->vol, ctx->firstaction);
				if (err)
					printf("* Redoing transaction"
							" set failed\n");
			}
			if (err)
				state = T_ERR;
			else
				if (playedactions == playcount)
					state = T_DONE;
				/* free queue */
			while (ctx->firstaction) {
				action = ctx->firstaction->next;
				free(ctx->firstaction);
				ctx->firstaction = action;
			}
			ctx->lastaction = (struct ACTION_RECORD*)NULL;
		}
		if (opts
		    && ((s64)(sle64_to_cpu(logr->this_lsn) - synced_lsn) <= 0)) {
			if (optv)
				printf("* Refreshing attributes\n");
// should refresh backward ?
			err = refresh_attributes(ctx->firstaction);
			if (!err)
				err = roothealth_analyze_transactions(ctx,
					ctx->firstaction);
			if (!err) {
				if (optv)
					printf("* Syncing actions %d->%d\n",
						(int)ctx->firstaction->num,
						(int)ctx->lastaction->num);
				err = play_redos(ctx->vol, ctx->firstaction);
			}
			if (!err)
				err = play_undos(ctx->vol, ctx->lastaction);
			if (err) {
				printf("* Syncing actions failed\n");
				state = T_ERR;
			} else
				state = T_DONE;
		}
	}
	return (state);
}


static void showheadrcrd(u32 blk, const RECORD_PAGE_HEADER *rph)
{
	s32 diff;

	if (optv) {
		printf("magic              %08lx\n",
			(long)le32_to_cpu(rph->magic));
		printf("usa_ofs            %04x\n",
			(int)le16_to_cpu(rph->usa_ofs));
		printf("usa_count          %04x\n",
			(int)le16_to_cpu(rph->usa_count));
		if (blk < 4)
			printf("file_offset        %016llx\n",
				(long long)sle64_to_cpu(rph->copy.file_offset));
		else {
			diff = sle64_to_cpu(rph->copy.last_lsn) - synced_lsn;
			printf("last_lsn           %016llx"
				" (synced%s%ld)\n",
				(long long)sle64_to_cpu(rph->copy.last_lsn),
				(diff < 0 ? "" : "+"),(long)diff);
		}
		printf("flags              %08lx\n",
			(long)le32_to_cpu(rph->flags));
		printf("page_count         %d\n",
			(int)le16_to_cpu(rph->page_count));
		printf("page_position      %d\n",
			(int)le16_to_cpu(rph->page_position));
		printf("next_record_offset %04x\n",
			(int)le16_to_cpu(rph->next_record_offset));
		printf("reserved4          %04x %04x %04x\n",
			(int)le16_to_cpu(rph->reserved[0]),
			(int)le16_to_cpu(rph->reserved[1]),
			(int)le16_to_cpu(rph->reserved[2]));
		diff = sle64_to_cpu(rph->last_end_lsn) - synced_lsn;
		printf("last_end_lsn       %016llx (synced%s%ld)\n",
			(long long)sle64_to_cpu(rph->last_end_lsn),
			(diff < 0 ? "" : "+"),(long)diff);
		printf("usn                %04x\n",
			(int)getle16(rph,le16_to_cpu(rph->usa_ofs)));
		printf("\n");
	} else {
		if (optt) {
			const char *state;

			state = commitment(sle64_to_cpu(rph->copy.last_lsn));
			diff = sle64_to_cpu(rph->copy.last_lsn) - synced_lsn;
			printf("   last        %016llx (synced%s%ld) %s\n",
				(long long)sle64_to_cpu(rph->copy.last_lsn),
				(diff < 0 ? "" : "+"),(long)diff, state);
			state = commitment(sle64_to_cpu(rph->last_end_lsn));
			diff = sle64_to_cpu(rph->last_end_lsn) - synced_lsn;
			printf("   last_end    %016llx (synced%s%ld) %s\n",
				(long long)sle64_to_cpu(rph->last_end_lsn),
				(diff < 0 ? "" : "+"),(long)diff, state);
		}
	}
}

/*
 *		Analyze and display an action overlapping log blocks
 *
 *	Returns the position of first action in next block. If this is
 *	greater than a block size (for actions overlapping more than
 *	two blocks), then some blocks have to be skipped.
 *
 *	Returns 0 in case of error
 */

static u16 overlapshow(CONTEXT *ctx, u16 k, u32 blk, const struct BUFFER *buf,
			const struct BUFFER *nextbuf)
{
	const LOG_RECORD *logr;
	const char *data;
	const char *nextdata;
	char *fullrec;
	u32 size;
	u32 nextspace;
	u32 space;
	BOOL likely;
	u16 blkheadsz;

	data = buf->block.data;
	logr = (const LOG_RECORD*)&data[k];
	size = le32_to_cpu(logr->client_data_length) + LOG_RECORD_HEAD_SZ;
	blkheadsz = buf->headsz;
	if (nextbuf && (blk >= BASEBLKS)) {
		nextdata = nextbuf->block.data;
		space = blocksz - k;
		nextspace = blocksz - blkheadsz;
		if ((space >= LOG_RECORD_HEAD_SZ)
		    && (size > space)) {
			fullrec = (char*)malloc(size);
			if (size <= (space + nextspace)) {
				/* Overlap on two blocks */
				memcpy(fullrec,&data[k],space);
				memcpy(&fullrec[space],
					nextdata + blkheadsz,
					size - space);
				likely = likelyop((LOG_RECORD*)fullrec, size);
				actionnum++;
				if (optv) {
					printf("\nOverlapping record %u at 0x%x"
						" size %d (next at 0x%x)\n",
						(int)actionnum,(int)k,
						(int)size, (int)(k + size));
					printf("Overlap marked for block %ld"
						" space %d likely %d\n",
						(long)blk,(int)space,likely);
				}
				if (likely)
					showlogr(ctx, k,
						(LOG_RECORD*)fullrec);
				else
					printf("** Skipping unlikely"
						" overlapping record\n");
				k += size - blocksz + blkheadsz;
			} else {
				const struct BUFFER *midbuf;
				int skip;
				u32 next;
				u32 pos;
				int i;

			/*
			 * The maximum size of of log record is 131104
			 * (when both offset and length are 65528 for
			 * redo or undo).
			 * So up to 33 log blocks (useful size 4032)
			 * could be needed. However never both undo and
			 * redo have been found big, and 17 should be
			 * the real maximum.
			 */
				if (optv)
					printf("More than two blocks required"
						" (size %lu)\n",(long)size);
				memcpy(fullrec,&data[k],space);

				skip = (size - space - 1)/nextspace;
				pos = space;
				likely = TRUE;
				for (i=1; (i<=skip) && likely; i++) {
					midbuf = read_buffer(ctx, blk + i);
					if (midbuf) {
						memcpy(&fullrec[pos],
							&midbuf->block
							    .data[blkheadsz],
							nextspace);
						pos += nextspace;
					} else
						likely = FALSE;
				}
				if (pos >= size) {
					printf("** Error : bad big overlap"
						" pos %d size %d\n",
						(int)pos,(int)size);
					likely = FALSE;
				}
				midbuf = read_buffer(ctx, blk + skip + 1);
				if (midbuf)
					memcpy(&fullrec[pos],
						&midbuf->block.data[blkheadsz],
						size - pos);
				else
					likely = FALSE;
				if (!likelyop((LOG_RECORD*)fullrec, size))
					likely = FALSE;
				actionnum++;
				if (optv) {
					printf("\nBig overlapping record %u at "
						"0x%x size %u (next at 0x%x)\n",
						(int)actionnum,(int)k,(int)size,
						(int)(k + size));
					printf("Overlap marked for block %ld"
						" space %d likely %d\n",
						(long)blk,(int)space,likely);
				}
				if (likely)
					showlogr(ctx, k,
						(LOG_RECORD*)fullrec);
				else
					printf("** Skipping unlikely"
						" overlapping record\n");
				/* next and skip are only for displaying */
				next = (size - space) % nextspace
							+ blkheadsz;
				if ((blocksz - next) < LOG_RECORD_HEAD_SZ)
					next = blkheadsz;
				if (next == blkheadsz)
					skip++;
				if (optv)
					printf("Next record expected in"
						" block %lu index 0x%x\n",
						(long)(blk + skip + 1),next);
					/* Quick check, with no consequences */
				if (firstrecord(skip,buf,buf) != next)
					printf("** Error next != firstrecord"
						" after block %d\n",blk);
				k += size - blocksz + blkheadsz;
			}
			if (!likely)
				k = 0;
			else
				if (!k)
					printf("* Bad return from overlap()\n");
			free(fullrec);
		} else {
			/* No conditions for overlap, usually a new session */
			printf("* No block found overlapping on block %d\n",
					(int)blk);
			k = 0;
		}
	} else {
		/* blocks 2, 3 and the last one have no next block */
		k = 0;
	}
	return (k);
}

/*
 *		Analyze and forward display the actions in a log block
 *
 *	Returns the position of first action in next block. If this is
 *	greater than a block size, then some blocks have to be skipped.
 *
 *	Returns 0 in case of error
 */

static u16 forward_rcrd(CONTEXT *ctx, u32 blk, u16 pos,
			const struct BUFFER *buf, const struct BUFFER *nextbuf)
{
	const RECORD_PAGE_HEADER *rph;
	const LOG_RECORD *logr;
	const char *data;
	u16 k;
	u16 endoff;
	BOOL stop;

	rph = &buf->block.record;
	if (rph && (rph->magic == magic_RCRD)) {
		data = buf->block.data;
		showheadrcrd(blk, rph);
		k = buf->headsz;
		if ((k < pos) && (pos < blocksz)) {
			k = ((pos - 1) | 7) + 1;
		}
// TODO check bad start > blocksz - 48
		logr = (const LOG_RECORD*)&data[k];
		stop = FALSE;
		if (!likelyop(logr, blocksz - k)) {
			if (optv)
				printf("* Bad start 0x%x for block %d\n",
					(int)pos,(int)blk);
			k = searchlikely(buf);
			if ((k + sizeof(LOG_RECORD)) > blocksz) {
				printf("No likely full record in block %lu\n",
						(unsigned long)blk);
		      /* there can be a partial one */
				k = le16_to_cpu(rph->next_record_offset);
				if ((k < (u16)sizeof(RECORD_PAGE_HEADER))
				    || ((blocksz - k) < LOG_RECORD_HEAD_SZ))
					stop = TRUE;
			} else {
				if (optv)
					printf("First record computed at"
						" offset 0x%x\n", (int)k);
			}
		}
		while (!stop) {
			s32 size;

			logr = (const LOG_RECORD*)&data[k];
			size = le32_to_cpu(logr->client_data_length)
						+ LOG_RECORD_HEAD_SZ;
			if ((size < MINRECSIZE)
			    || (size > MAXRECSIZE)
			    || (size & 7)) {
				printf("** Bad record size %ld in block %ld"
					" offset 0x%x\n",
					(long)size, (long)buf->num, (int)k);
				showlogr(ctx, k, logr);
				k = 0;
				stop = TRUE;
			} else {
				endoff = le16_to_cpu(rph->next_record_offset);
				if (((u32)(k + size) <= blocksz)
				    && ((u32)(k + size) <= endoff)) {
					actionnum++;
					if (optv) {
						printf("\n* log action %u at"
							" 0x%x size %d (next"
							" at 0x%x)\n",
							actionnum,k,size,
							k + size);
					}
					showlogr(ctx, k, logr);
					if (!logr->client_data_length) {
						printf("** Bad"
						    " client_data_length\n");
						stop = TRUE;
					}
					k += size;
					if ((blocksz - k)
							< LOG_RECORD_HEAD_SZ) {
						k = nextbuf->headsz;
						stop = TRUE;
					}
				} else {
					k = overlapshow(ctx, k, blk,
								buf, nextbuf);
					stop = TRUE;
				}
			}
		}
	} else {
		printf("** Not a RCRD record, MAGIC 0x%08lx\n",
			(long)le32_to_cpu(rph->magic));
		k = 0;
	}
	return (k);
}

/*
 *                Display a restart page
 */

static void showrest(const RESTART_PAGE_HEADER *rest)
{
	const RESTART_AREA *resa;
	const LOG_CLIENT_RECORD *rcli;
	const char *data;

	data = (const char*)rest;
	if ((rest->magic == magic_RSTR)
			|| (rest->magic == magic_CHKD)) {
		if (optv) {
			printf("magic                  %08lx\n",
				(long)le32_to_cpu(rest->magic));
			printf("usa_ofs                %04x\n",
				(int)le16_to_cpu(rest->usa_ofs));
			printf("usa_count              %04x\n",
				(int)le16_to_cpu(rest->usa_count));
			printf("chkdsk_lsn             %016llx\n",
				(long long)sle64_to_cpu(rest->chkdsk_lsn));
			printf("system_page_size       %08lx\n",
				(long)le32_to_cpu(rest->system_page_size));
			printf("log_page_size          %08lx\n",
				(long)le32_to_cpu(rest->log_page_size));
			printf("restart_area_offset    %04x\n",
				(int)le16_to_cpu(rest->restart_area_offset));
			printf("minor_vers             %d\n",
				(int)sle16_to_cpu(rest->minor_ver));
			printf("major_vers             %d\n",
				(int)sle16_to_cpu(rest->major_ver));
			printf("usn                    %04x\n",
				(int)le16_to_cpu(rest->usn));
			printf("\n");
		} else {
			if (optt)
				printf("    chkdsk         %016llx\n",
				    (long long)sle64_to_cpu(rest->chkdsk_lsn));
		}
		resa = (const RESTART_AREA*)
				&data[le16_to_cpu(rest->restart_area_offset)];
		if (optv) {
			printf("current_lsn            %016llx\n",
				(long long)sle64_to_cpu(resa->current_lsn));
			printf("log_clients            %04x\n",
				(int)le16_to_cpu(resa->log_clients));
			printf("client_free_list       %04x\n",
				(int)le16_to_cpu(resa->client_free_list));
			printf("client_in_use_list     %04x\n",
				(int)le16_to_cpu(resa->client_in_use_list));
			printf("flags                  %04x\n",
				(int)le16_to_cpu(resa->flags));
			printf("seq_number_bits        %08lx\n",
				(long)le32_to_cpu(resa->seq_number_bits));
			printf("restart_area_length    %04x\n",
				(int)le16_to_cpu(resa->restart_area_length));
			printf("client_array_offset    %04x\n",
				(int)le16_to_cpu(resa->client_array_offset));
			printf("file_size              %016llx\n",
				(long long)sle64_to_cpu(resa->file_size));
			printf("last_lsn_data_len      %08lx\n",
				(long)le32_to_cpu(resa->last_lsn_data_length));
			printf("record_length          %04x\n",
				(int)le16_to_cpu(resa->log_record_header_length));
			printf("log_page_data_offs     %04x\n",
				(int)le16_to_cpu(resa->log_page_data_offset));
			printf("restart_log_open_count %08lx\n",
				(long)le32_to_cpu(resa->restart_log_open_count));
			printf("\n");
		} else {
			if (optt)
				printf("    latest         %016llx\n",
				    (long long)sle64_to_cpu(resa->current_lsn));
		}

		rcli = (const LOG_CLIENT_RECORD*)
				&data[le16_to_cpu(rest->restart_area_offset)
				+ le16_to_cpu(resa->client_array_offset)];
		if (optv) {
			printf("oldest_lsn             %016llx\n",
				(long long)sle64_to_cpu(rcli->oldest_lsn));
			printf("client_restart_lsn     %016llx\n",
				(long long)sle64_to_cpu(rcli->client_restart_lsn));
			printf("prev_client            %04x\n",
				(int)le16_to_cpu(rcli->prev_client));
			printf("next_client            %04x\n",
				(int)le16_to_cpu(rcli->next_client));
			printf("seq_number             %04x\n",
				(int)le16_to_cpu(rcli->seq_number));
			printf("client_name_length     %08x\n",
				(int)le32_to_cpu(rcli->client_name_length));
			showname("client_name            ",
				(const char*)rcli->client_name,
				le32_to_cpu(rcli->client_name_length) >> 1);
		} else {
			if (optt) {
				printf("    synced         %016llx\n",
					(long long)sle64_to_cpu(
						rcli->oldest_lsn));
				printf("    committed      %016llx\n",
					(long long)sle64_to_cpu(
						rcli->client_restart_lsn));
			}
		}
	} else
		printf("Not a RSTR or CHKD record, MAGIC 0x%08lx\n",
			(long)le32_to_cpu(rest->magic));
}

static BOOL dorest(CONTEXT *ctx, unsigned long blk,
			const RESTART_PAGE_HEADER *rph, BOOL initial)
{
	const RESTART_AREA *resa;
	const LOG_CLIENT_RECORD *rcli;
	const char *data;
	s64 diff;
	int offs;
	int size;
	BOOL change;
	BOOL dirty;

	data = (const char*)rph;
	offs = le16_to_cpu(rph->restart_area_offset);
	resa = (const RESTART_AREA*)&data[offs];
	rcli = (const LOG_CLIENT_RECORD*)&data[offs
				+ le16_to_cpu(resa->client_array_offset)];
	if (initial) {
		/* Information from block initially found best */
		latest_lsn = sle64_to_cpu(resa->current_lsn);
		committed_lsn = sle64_to_cpu(rcli->client_restart_lsn);
		synced_lsn = sle64_to_cpu(rcli->oldest_lsn);
		memcpy(&log_header, rph,
				sizeof(RESTART_PAGE_HEADER));
		offs = le16_to_cpu(log_header.restart_area_offset);
		memcpy(&restart, &data[offs],
				sizeof(RESTART_AREA));
		offs += le16_to_cpu(restart.client_array_offset);
		memcpy(&client, &data[offs],
				sizeof(LOG_CLIENT_RECORD));
		dirty = !(resa->flags & RESTART_VOLUME_IS_CLEAN);
		if (optv || optt)
			printf("* Using initial restart page,"
				" syncing from 0x%llx, %s\n",
				(long long)synced_lsn,
				(dirty ? "dirty" : "clean"));
			 /* Get the block page size */
		blocksz = le32_to_cpu(rph->log_page_size);
		if (optv)
			printf("* Block size %ld bytes\n", (long)blocksz);
		blockbits = 1;
		while ((u32)(1 << blockbits) < blocksz)
			blockbits++;
	} else {
		size = offs + le16_to_cpu(resa->restart_area_length);
		if (optv) {
			if (optv >= 2)
				hexdump(data,size);
			printf("* RSTR in block %ld 0x%lx (addr 0x%llx)\n",
					(long)blk,(long)blk,
					(long long)loclogblk(ctx, blk));
		} else {
			if (optt)
				printf("restart %ld\n",(long)blk);
		}
		showrest(rph);
		/* Information from an older restart block if requested */
		dirty = !(restart.flags & RESTART_VOLUME_IS_CLEAN);
		diff = sle64_to_cpu(rcli->client_restart_lsn) - committed_lsn;
		if (ctx->vol) {
			change = (opts > 1) && (diff < 0);
		} else {
			change = (opts > 1 ? diff < 0 : diff > 0);
		}
		if (change) {
			committed_lsn = sle64_to_cpu(rcli->client_restart_lsn);
			synced_lsn = sle64_to_cpu(rcli->oldest_lsn);
			latest_lsn = sle64_to_cpu(resa->current_lsn);
			memcpy(&log_header, rph,
					sizeof(RESTART_PAGE_HEADER));
			offs = le16_to_cpu(log_header.restart_area_offset);
			memcpy(&restart, &data[offs],
					sizeof(RESTART_AREA));
			offs += le16_to_cpu(restart.client_array_offset);
			memcpy(&client, &data[offs],
					sizeof(LOG_CLIENT_RECORD));
			dirty = !(resa->flags & RESTART_VOLUME_IS_CLEAN);
			if (optv || optt)
				printf("* Using %s restart page,"
					" syncing from 0x%llx, %s\n",
					(diff < 0 ? "older" : "newer"),
					(long long)synced_lsn,
					(dirty ? "dirty" : "clean"));
		}
	}
	restart_lsn = synced_lsn;
	offset_mask = ((u64)1 << (64 - le32_to_cpu(restart.seq_number_bits)))
				- (1 << (blockbits - 3));
	return (dirty);
}

static int roothealth_bytes_zero(const unsigned char *bytes, size_t length)
{
	while (length--)
		if (*bytes++)
			return 0;
	return 1;
}

static int roothealth_restart_lsn_valid(uint64_t lsn, uint32_t sequence_bits,
		uint64_t file_size, int allow_zero)
{
	uint32_t offset_bits;
	uint64_t mask;

	if (!lsn)
		return allow_zero;
	if (!sequence_bits || sequence_bits >= 64U)
		return 0;
	offset_bits = 64U - sequence_bits;
	mask = offset_bits == 64U ? UINT64_MAX :
		((((uint64_t)1) << offset_bits) - 1U);
	return (lsn & ~mask) && (lsn & mask) < file_size / 8U;
}

int roothealth_restart_page_supported(const RESTART_PAGE_HEADER *header,
		u64 expected_logfile_size)
{
	const unsigned char *raw = (const unsigned char *)header;
	const RESTART_AREA *area;
	const LOG_CLIENT_RECORD *client_record;
	uint64_t current_lsn, oldest_lsn, client_restart_lsn, size_for_bits;
	uint32_t page_size, log_page_size, sequence_bits;
	uint32_t area_offset, area_length, client_offset;
	uint16_t free_client, in_use_client, flags, usa_offset;
	uint16_t major, minor;
	uint32_t expected_sequence_bits = 67U;

	if (!header)
		return 0;
	page_size = le32_to_cpu(header->system_page_size);
	log_page_size = le32_to_cpu(header->log_page_size);
	area_offset = le16_to_cpu(header->restart_area_offset);
	usa_offset = le16_to_cpu(header->usa_ofs);
	major = le16_to_cpu(header->major_ver);
	minor = le16_to_cpu(header->minor_ver);
	if (header->magic != magic_RSTR ||
		!((usa_offset == offsetof(RESTART_PAGE_HEADER, usn)) ||
		  (usa_offset == sizeof(*header))) ||
		le16_to_cpu(header->usa_count) != 9U ||
		sle64_to_cpu(header->chkdsk_lsn) ||
		!((major == 1U && minor == 1U) ||
		  (major == 2U && minor == 0U)) ||
		page_size != ROOTHEALTH_REPLAY_PAGE_SIZE ||
		log_page_size != ROOTHEALTH_REPLAY_PAGE_SIZE ||
		(area_offset & 7) || area_offset > page_size - sizeof(*area) ||
		usa_offset + 18U > area_offset)
		return 0;
	area = (const RESTART_AREA *)(raw + area_offset);
	area_length = le16_to_cpu(area->restart_area_length);
	client_offset = le16_to_cpu(area->client_array_offset);
	sequence_bits = le32_to_cpu(area->seq_number_bits);
	current_lsn = sle64_to_cpu(area->current_lsn);
	free_client = le16_to_cpu(area->client_free_list);
	in_use_client = le16_to_cpu(area->client_in_use_list);
	flags = le16_to_cpu(area->flags);
	if (area_length < sizeof(*area) || area_length > page_size - area_offset ||
		(client_offset & 7U) || client_offset < 64U ||
		client_offset > area_length || sizeof(LOG_CLIENT_RECORD) !=
			area_length - client_offset ||
		le16_to_cpu(area->log_clients) != 1U ||
		!((free_client == 0U && in_use_client == LOGFILE_NO_CLIENT_CPU) ||
		  (free_client == LOGFILE_NO_CLIENT_CPU && in_use_client == 0U)) ||
		(flags & ~3U) || !current_lsn || !sequence_bits ||
		sequence_bits >= 64 ||
		sle64_to_cpu(area->file_size) < RH_REPLAY_MIN_LOGFILE_SIZE ||
		(uint64_t)sle64_to_cpu(area->file_size) >
			RH_REPLAY_MAX_LOGFILE_SIZE ||
		((uint64_t)sle64_to_cpu(area->file_size) %
			RH_REPLAY_PAGE_SIZE) ||
		(uint64_t)sle64_to_cpu(area->file_size) != expected_logfile_size ||
		le16_to_cpu(area->log_record_header_length) != LOG_RECORD_HEAD_SZ ||
		le16_to_cpu(area->log_page_data_offset) != 0x40U ||
		le32_to_cpu(area->reserved) ||
		le32_to_cpu(area->last_lsn_data_length) >
			RH_REPLAY_MAX_ACTION_SIZE - LOG_RECORD_HEAD_SZ ||
		!roothealth_bytes_zero(raw + area_offset + sizeof(*area),
			client_offset - sizeof(*area)))
		return 0;
	size_for_bits = (uint64_t)sle64_to_cpu(area->file_size);
	while (size_for_bits) {
		size_for_bits >>= 1;
		--expected_sequence_bits;
	}
	if (sequence_bits != expected_sequence_bits)
		return 0;
	size_for_bits = (uint64_t)sle64_to_cpu(area->file_size);
	client_record = (const LOG_CLIENT_RECORD *)(raw + area_offset + client_offset);
	oldest_lsn = sle64_to_cpu(client_record->oldest_lsn);
	client_restart_lsn = sle64_to_cpu(client_record->client_restart_lsn);
	if (!roothealth_restart_lsn_valid(current_lsn, sequence_bits,
			size_for_bits, 0) ||
		!roothealth_restart_lsn_valid(oldest_lsn, sequence_bits,
			size_for_bits, 1) ||
		!roothealth_restart_lsn_valid(client_restart_lsn, sequence_bits,
			size_for_bits, 1) ||
		oldest_lsn > current_lsn || client_restart_lsn > current_lsn ||
		(client_restart_lsn && oldest_lsn > client_restart_lsn) ||
		le16_to_cpu(client_record->seq_number) == UINT16_MAX ||
		le16_to_cpu(client_record->prev_client) != LOGFILE_NO_CLIENT_CPU ||
		le16_to_cpu(client_record->next_client) != LOGFILE_NO_CLIENT_CPU ||
		!roothealth_bytes_zero(client_record->reserved,
			sizeof(client_record->reserved)) ||
		le32_to_cpu(client_record->client_name_length) != 8U ||
		le16_to_cpu(client_record->client_name[0]) != 'N' ||
		le16_to_cpu(client_record->client_name[1]) != 'T' ||
		le16_to_cpu(client_record->client_name[2]) != 'F' ||
		le16_to_cpu(client_record->client_name[3]) != 'S' ||
		!roothealth_bytes_zero((const unsigned char *)&client_record->client_name[4],
			sizeof(client_record->client_name) - 4U * sizeof(ntfschar)))
		return 0;
	return 1;
}

static int roothealth_restart_profile_valid(const RESTART_PAGE_HEADER *header)
{
	return roothealth_restart_page_supported(header, logfilesz);
}

/*
 *		Read and process the first restart block
 *
 *	In full mode, both restart page are silently analyzed by the
 *	library and the most recent readable one is used to define the
 *	sync parameters.
 *
 *	Returns the first restart buffer
 *		or NULL if the restart block is not valid
 */


static const struct BUFFER *read_restart(CONTEXT *ctx)
{
	const struct BUFFER *buf;
	BOOL bad;
	int blk;
	int major, minor;

	bad = FALSE;
	for (blk=0; blk<BASEBLKS2; blk++)
		redirect[blk] = 0;
	log_major = 0; /* needed for reading into a buffer */
	if (ctx->vol) {
		RESTART_PAGE_HEADER *rph;

		rph = (RESTART_PAGE_HEADER*)NULL;
		/* Full mode : use the restart page selected by the library */
			if (ntfs_check_logfile(log_na, &rph)) {
			/* rph is left unchanged for a wiped out log file */
				if (rph && roothealth_restart_profile_valid(rph)) {
					dorest(ctx, 0, rph, TRUE);
					free(rph);
					buf = read_buffer(ctx,0);
				} else {
					free(rph);
					buf = (const struct BUFFER*)NULL;
					printf("** Unsupported or invalid restart page\n");
			}
		} else {
			buf = (const struct BUFFER*)NULL;
			printf("** Could not get any restart page\n");
		}
	} else {
		/* Reduced mode : rely on first restart page */
		blockbits = BLOCKBITS;	/* Until the correct value is read */
		blocksz = 1L << blockbits;
		buf = read_buffer(ctx,0);
	}
	if (buf) {
		NTFS_RECORD_TYPES magic;

		if (!roothealth_restart_profile_valid(&buf->block.restart))
			bad = TRUE;
		magic = buf->block.restart.magic;
		switch (magic) {
		case magic_RSTR :
			break;
		case magic_CHKD :
			printf("** The log file has been obsoleted by chkdsk\n");
			bad = TRUE;
			break;
		case magic_empty :
			printf("** The log file has been wiped out\n");
			bad = TRUE;
			break;
		default :
			printf("** Invalid restart block\n");
			bad = TRUE;
			break;
		}
		if (!bad && !ctx->vol)
			dorest(ctx, 0, &buf->block.restart, TRUE);
		major = sle16_to_cpu(buf->block.restart.major_ver);
		minor = sle16_to_cpu(buf->block.restart.minor_ver);
		if (!(((major == 1) && ((minor == 0) || (minor == 1))) ||
				((major == 2) && (minor == 0)))) {
				printf("** Unsupported $LogFile version %d.%d\n",
					major, minor);
				bad = TRUE;
		}
		log_major = major;
		if (bad) {
			buf = (const struct BUFFER*)NULL;
		}
	}
	return (buf);
}

/*
 *		Mark the logfile as synced
 */

static int roothealth_plan_attr_write(ntfs_attr *na, u64 pos, size_t length,
		const unsigned char *data, enum rh_write_kind kind)
{
	unsigned char *cluster;
	int err = 1;

	if (!rh_replay_writer || !na || pos > (u64)na->data_size ||
		length > (u64)na->data_size - pos)
		return 1;
	cluster = malloc(clustersz);
	if (!cluster)
		return 1;
	err = 0;
	while (length && !err) {
		struct rh_write_semantic_target semantic;
		u64 vcn = pos >> clusterbits;
		u64 within = pos & (clustersz - 1);
		size_t chunk = clustersz - within;
		LCN lcn = roothealth_attr_vcn_to_lcn(na, vcn);
		u64 raw;

		if (chunk > length)
			chunk = length;
		if (lcn < 0) {
			err = 1;
			break;
		}
		raw = (u64)lcn << clusterbits;
		if (rh_writer_read(rh_replay_writer, raw, clustersz, cluster)) {
			err = 1;
			break;
		}
		memcpy(cluster + within, data, chunk);
		if (roothealth_build_native_attr_target(na, (VCN)vcn, lcn, raw,
				clustersz, kind, &semantic) ||
			rh_writer_plan_typed(rh_replay_writer, kind, raw, clustersz,
				cluster, &semantic)) {
			err = 1;
			break;
		}
		pos += chunk;
		data += chunk;
		length -= chunk;
	}
	free(cluster);
	return err;
}

static int roothealth_plan_clean_restart_pages(
		CONTEXT *ctx __attribute__((unused)))
{
	char *buffer;
	int off;
	int err;

	err = 1;
	buffer = (char*)malloc(blocksz);
	if (buffer) {
		memset(buffer, 0, blocksz);
		restart.client_in_use_list = LOGFILE_NO_CLIENT;
		restart.client_free_list = const_cpu_to_le16(0);
		restart.flags |= RESTART_VOLUME_IS_CLEAN;
		client.oldest_lsn = cpu_to_sle64(restart_lsn);
		memcpy(buffer, &log_header,
					sizeof(RESTART_PAGE_HEADER));
		off = le16_to_cpu(log_header.restart_area_offset);
		memcpy(&buffer[off], &restart,
					sizeof(RESTART_AREA));
		off += le16_to_cpu(restart.client_array_offset);
		memcpy(&buffer[off], &client,
					sizeof(LOG_CLIENT_RECORD));
		if (roothealth_restart_profile_valid(
				(RESTART_PAGE_HEADER *)buffer) &&
				!ntfs_mst_pre_write_fixup((NTFS_RECORD*)buffer, blocksz) &&
				!roothealth_plan_attr_write(log_na, 0, blocksz,
					(const unsigned char *)buffer,
					RH_WRITE_LOGFILE_RESTART) &&
				!roothealth_plan_attr_write(log_na,
					(u64)1 << blockbits, blocksz,
					(const unsigned char *)buffer,
					RH_WRITE_LOGFILE_RESTART)) {
			err = 0;
			rh_restart_pages_planned = 2;
		}
		free(buffer);
	}
	return (err);
}

/*
 *		Determine the most recent valid record block
 */

static const struct BUFFER *best_start(const struct BUFFER *buf,
				const struct BUFFER *altbuf)
{
	const struct BUFFER *best;
	const RECORD_PAGE_HEADER *head;
	const RECORD_PAGE_HEADER *althead;
	s64 diff;

	if (!buf || !altbuf)
		best = (buf ? buf : altbuf);
	else {
		head = &buf->block.record;
		althead = &altbuf->block.record;
		/* determine most recent, caring for wraparounds */
		diff = sle64_to_cpu(althead->last_end_lsn)
					- sle64_to_cpu(head->last_end_lsn);
		if (diff > 0)
			best = altbuf;
		else
			best = buf;
	}
	if (best && (best->block.record.magic != magic_RCRD))
		best = (const struct BUFFER*)NULL;
	return (best);
}

/*
 *                 Interpret the boot data
 *
 *	Probably not needed any more, use ctx->vol
 */

static BOOL getboot(const char *buf)
{
	u64 sectors;
	u64 clusters;
	u16 sectpercluster;
	BOOL ok;

	ok = TRUE;
	/* Beware : bad alignment */
	bytespersect = (buf[11] & 255) + ((buf[12] & 255) << 8);
	sectpercluster = buf[13] & 255;
	clustersz = bytespersect * (u32)sectpercluster;
	clusterbits = 1;
	while ((u32)(1 << clusterbits) < clustersz)
		clusterbits++;
	sectors = getle64(buf, 0x28);
	clusters = sectors/sectpercluster;
	mftlcn = getle64(buf, 0x30);
	if (buf[0x40] & 0x80)
		mftrecsz = 1 << (16 - (buf[0x40] & 15));
	else
		mftrecsz = (buf[0x40] & 127)*clustersz;
	mftrecbits = 1;
	while ((u32)(1 << mftrecbits) < mftrecsz)
		mftrecbits++;
	if (optv) {
		if ((long long)sectors*bytespersect > 10000000000LL)
			printf("Capacity %lld bytes (%lld GB)\n",
				(long long)sectors*bytespersect,
				(long long)sectors*bytespersect/1000000000);
		else
			printf("Capacity %lld bytes (%lld MB)\n",
				(long long)sectors*bytespersect,
				(long long)sectors*bytespersect/1000000);
		printf("sectors %lld (0x%llx), sector size %d\n",
				(long long)sectors,(long long)sectors,
				(int)bytespersect);
		printf("clusters %lld (0x%llx), cluster size %d (%d bits)\n",
				(long long)clusters,(long long)clusters,
				(int)clustersz,(int)clusterbits);
		printf("MFT at cluster %lld (0x%llx), entry size %lu\n",
				(long long)mftlcn,(long long)mftlcn,
				(unsigned long)mftrecsz);
		if (mftrecsz > clustersz)
			printf("%ld clusters per MFT entry\n",
				(long)(mftrecsz/clustersz));
		else
			printf("%ld MFT entries per cluster\n",
				(long)(clustersz/mftrecsz));
	}
	return (ok);
}

static int locatelogfile(CONTEXT *ctx)
{
	int err;
	s64 size;

	err = 1;
	log_ni = ntfs_inode_open(ctx->vol, FILE_LogFile);
	if (log_ni) {
		log_na = ntfs_attr_open(log_ni, AT_DATA, AT_UNNAMED, 0);
		if (log_na) {
			size = log_na->data_size;
			if (size >= RH_REPLAY_MIN_LOGFILE_SIZE &&
				(uint64_t)size <= ROOTHEALTH_MAX_LOGFILE_SIZE &&
				size <= UINT32_MAX &&
				!(size % RH_REPLAY_PAGE_SIZE)) {
				logfilesz = (u32)size;
				err = 0;
			}
		}
	}
	return (err);
}

/*
 *                 Get basic volume data
 *
 *	Locate the MFT and Logfile
 *	Not supposed to read the first log block...
 */

static BOOL getvolumedata(CONTEXT *ctx, char *boot)
{
	const RESTART_AREA *rest;
	BOOL ok;

	ok = FALSE;
	rest = (const RESTART_AREA*)NULL;
	if (ctx->vol) {
		getboot(boot);
		mftlcn = ctx->vol->mft_lcn;
		mftcnt = ctx->vol->mft_na->data_size/mftrecsz;
		if (!locatelogfile(ctx))
			ok = TRUE;
		else {
			fprintf(stderr,"** Could not read the log file\n");
		}
	}
// TODO get rest ?, meaningful ?
	if (ok && rest) {
		if (rest->client_in_use_list
		   || !(rest->flags & const_cpu_to_le16(2)))
			printf("Volume was not unmounted safely\n");
		else
			printf("Volume was unmounted safely\n");
		if (le16_to_cpu(rest->client_in_use_list) > 1)
			printf("** multiple clients not implemented\n");
	}
	return (ok);
}

/*
 *		Open the complete volume and get its parameters
 *
 *	Returns TRUE if successful
 */

static BOOL open_volume(CONTEXT *ctx, const char *device_name,
		ntfs_volume *mounted_volume)
{
	union {
		char buf[1024];
		 /* alignment may be needed in getboot() */
		long long force_align;
	} boot;
	BOOL ok;

	ok =FALSE;
	ctx->vol = (ntfs_volume*)NULL;
	ctx->file = (FILE*)NULL;
	ctx->vol = mounted_volume ? mounted_volume :
		ntfs_mount(device_name, NTFS_MNT_RDONLY |
			NTFS_MNT_FORENSIC | NTFS_MNT_FS_NO_REPAIR);
	if (ctx->vol) {
		if (NDevReadOnly(ctx->vol->dev) &&
			ntfs_pread(ctx->vol->dev, 0, sizeof(boot.buf), boot.buf) ==
				(s64)sizeof(boot.buf))
			ok = getvolumedata(ctx, boot.buf);
		if (!ok) {
			if (!mounted_volume)
				ntfs_umount(ctx->vol, TRUE);
			ctx->vol = (ntfs_volume*)NULL;
		}
	}
	return (ok);
}

static u16 dorcrd(CONTEXT *ctx, u32 blk, u16 pos, const struct BUFFER *buf,
			const struct BUFFER *nextbuf)
{
	if (optv) {
		if (optv >= 2)
			hexdump(buf->block.data,blocksz);
		printf("* RCRD in block %ld 0x%lx (addr 0x%llx)"
			" from pos 0x%x\n",
			(long)blk,(long)blk,
			(long long)loclogblk(ctx, blk),(int)pos);
	} else {
		if (optt)
			printf("block %ld\n",(long)blk);
	}
	return (forward_rcrd(ctx, blk, pos, buf, nextbuf));
}

/*
 *		Concatenate and process a record overlapping on several blocks
 */

static u32 roothealth_next_record_page(u32 page)
{
	u32 pages = logfilesz >> blockbits;
	u32 first = log_major < 2 ? ROOTHEALTH_V1_FIRST_PAGE :
		ROOTHEALTH_V2_FIRST_PAGE;

	++page;
	return page < pages ? page : first;
}

static int roothealth_transfer_edge_valid(const struct BUFFER *current,
		const struct BUFFER *next)
{
	const RECORD_PAGE_HEADER *left;
	const RECORD_PAGE_HEADER *right;
	u16 count;
	u16 position;

	if (!current || !next)
		return 0;
	left = &current->block.record;
	right = &next->block.record;
	count = le16_to_cpu(left->page_count);
	position = le16_to_cpu(left->page_position);
	if (!count || !position || position > count)
		return 0;
	if (position < count)
		return le16_to_cpu(right->page_count) == count &&
			le16_to_cpu(right->page_position) == position + 1U;
	return le16_to_cpu(right->page_position) == 1U;
}

static int roothealth_reassemble_log_record(CONTEXT *ctx, u32 blk, u16 start,
		const struct BUFFER *first, unsigned char *record, size_t size,
		unsigned int *pages_used)
{
	const struct BUFFER *current = first;
	const struct BUFFER *next;
	const RECORD_PAGE_HEADER *header;
	size_t copied;
	u32 current_page = blk;
	unsigned int pages = 1;

	if (!ctx || !first || !record || size <= blocksz - start ||
		start < first->headsz || start > blocksz - sizeof(LOG_RECORD))
		return -1;
	copied = blocksz - start;
	memcpy(record, first->block.data + start, copied);
	if (!(le16_to_cpu(((const LOG_RECORD *)record)->log_record_flags) &
			LOG_RECORD_MULTI_PAGE))
		return -1;
	while (copied < size) {
		size_t available;
		size_t take;
		u16 next_offset;

		if (pages >= RH_REPLAY_MAX_RECORD_PAGES)
			return -1;
		current_page = roothealth_next_record_page(current_page);
		next = read_buffer(ctx, current_page);
		if (!next || next->block.record.magic != magic_RCRD ||
			next->headsz != 0x40U ||
			!roothealth_transfer_edge_valid(current, next))
			return -1;
		header = &next->block.record;
		available = blocksz - next->headsz;
		take = size - copied;
		if (take > available)
			take = available;
		memcpy(record + copied, next->block.data + next->headsz, take);
		copied += take;
		next_offset = le16_to_cpu(header->next_record_offset);
		if (copied < size) {
			if ((le32_to_cpu(header->flags) & 1U) || next_offset)
				return -1;
		} else if (!(le32_to_cpu(header->flags) & 1U) ||
			next_offset < next->headsz + take ||
			sle64_to_cpu(header->last_end_lsn) <
				sle64_to_cpu(((const LOG_RECORD *)record)->this_lsn)) {
			return -1;
		}
		current = next;
		++pages;
	}
	if (pages_used)
		*pages_used = pages;
	return 0;
}

static TRISTATE backoverlap(CONTEXT *ctx, int blk,
			const char *data, const char *nextdata, int k)
{
	const LOG_RECORD *logr;
	char *fullrec;
	s32 size;
	int space;
	TRISTATE state;
	unsigned int pages_used = 0;

	(void)nextdata;

	logr = (const LOG_RECORD*)&data[k];
	state = T_ERR;
	size = le32_to_cpu(logr->client_data_length) + LOG_RECORD_HEAD_SZ;
	space = blocksz - k;
	if ((space >= (int)sizeof(LOG_RECORD))
	    && (size > space)
	    && (size <= (s32)RH_REPLAY_MAX_ACTION_SIZE)) {
		fullrec = (char*)malloc(size);
		if (!fullrec)
			return T_ERR;
		if (roothealth_reassemble_log_record(ctx, (u32)blk, (u16)k,
				(const struct BUFFER *)read_buffer(ctx, (u32)blk),
				(unsigned char *)fullrec, (size_t)size, &pages_used) ||
			!likelyop((LOG_RECORD*)fullrec, (size_t)size)) {
			++rh_parse_errors;
			state = T_ERR;
		} else {
			++actionnum;
			state = T_OK;
		}
		if (optv) {
			printf("\nOverlapping backward action %d at 0x%x"
				" size %d across %u pages (next at 0x%x)\n",
				(int)actionnum,(int)k,
				(int)size,pages_used,(int)(k + size));
			printf("Overlap marked for block %ld space %d"
				" likely %d\n",
				(long)blk,(int)space,(state == T_OK));
		}
		if (state == T_OK) {
			if (optp || optu || opts)
				state = enqueue_action(ctx,
						(LOG_RECORD*)fullrec,
						size, actionnum,
						roothealth_record_source_offset(
							read_buffer(ctx, (u32)blk), (u16)k));
			if (state != T_ERR)
				showlogr(ctx, k, (LOG_RECORD*)fullrec);
		} else {
			/* Try to go on unless playing actions */
			if (optb && (state == T_ERR))
				state = T_OK;
		}
		free(fullrec);
	} else {
			/* Error conditions */
		if ((size < MINRECSIZE) ||
			(size > (s32)RH_REPLAY_MAX_ACTION_SIZE)) {
			printf("** Invalid record size %ld"
					" in block %ld\n",
					(long)size,(long)blk);
		} else
			printf("** Inconsistency : the final"
						" record in block %ld"
						" does not overlap\n",
						(long)blk);
			/* Do not abort, unless playing actions */
		state = (optb ? T_OK : T_ERR);
	}
	return (state);
}

static TRISTATE backward_rcrd(CONTEXT *ctx, u32 blk, int skipped,
                  const struct BUFFER *buf, const struct BUFFER *prevbuf,
                  const struct BUFFER *nextbuf)
{
	u16 poslist[75]; /* 4096/sizeof(LOG_RECORD) */
	const RECORD_PAGE_HEADER *rph;
	const RECORD_PAGE_HEADER *prevrph;
	const LOG_RECORD *logr;
	const char *data;
	const char *nextdata;
	BOOL stop;
	TRISTATE state;
	s32 size;
	int cnt;
	u16 k;
	u16 endoff;
	int j;
	u64 prior_lsn;

	state = T_ERR;
	rph = &buf->block.record;
	prevrph = (RECORD_PAGE_HEADER*)NULL;
	if (prevbuf)
		prevrph = &prevbuf->block.record;
	data = buf->block.data;
	if (rph && (rph->magic == magic_RCRD)
	    && (!prevrph || (prevrph->magic == magic_RCRD))) {
		if (optv) {
			if (optv >= 2)
				hexdump(data,blocksz);
			if (buf->rnum != blk)
				printf("* RCRD for block %ld 0x%lx"
				     " in block %ld (addr 0x%llx)\n",
				     (long)blk,(long)blk,(long)buf->rnum,
				     (long long)loclogblk(ctx, blk));
			else
				printf("* RCRD in block %ld 0x%lx (addr 0x%llx)\n",
				     (long)blk,(long)blk,
				     (long long)loclogblk(ctx, blk));
		} else {
			if (optt)
				printf("block %ld\n",(long)blk);
		}
		showheadrcrd(blk, rph);
		if (!prevbuf)
			k = buf->headsz;
		else
			k = firstrecord(skipped, buf, prevbuf);
		if (k > blocksz - LOG_RECORD_HEAD_SZ)
			return T_ERR;
		logr = (const LOG_RECORD*)&data[k];
		cnt = 0;
	   /* check whether there is at least one beginning of record */
		endoff = le16_to_cpu(rph->next_record_offset);
		if (k && ((k < endoff) || !endoff)) {
			logr = (const LOG_RECORD*)&data[k];
			size = (blocksz - k >= LOG_RECORD_HEAD_SZ) ?
				le32_to_cpu(logr->client_data_length) +
				LOG_RECORD_HEAD_SZ : 0;
			if (likelyop(logr, blocksz - k) &&
			    (!opts || !roothealth_guard_log_record(ctx, logr, size,
					roothealth_record_source_offset(buf, k), NULL))) {
				stop = FALSE;
				state = T_OK;
				if (optv)
					printf("First record checked"
						" at offset 0x%x\n", (int)k);
			} else {
				printf("** Bad first record in block %u at offset 0x%x\n",
								blk, (int)k);
				if (optv)
					showlogr(ctx, k,logr);
				k = searchlikely(buf);
				stop = !k;
				if (stop) {
					printf("** Could not recover,"
						" stopping at block %d\n",
						(int)blk);
					state = T_ERR;
				} else {
					/* Try to go on, unless running */
					if (optb)
						state = T_OK;
				}
			}
			while (!stop) {
				logr = (const LOG_RECORD*)&data[k];
				size = le32_to_cpu(logr->client_data_length)
						+ LOG_RECORD_HEAD_SZ;
				if ((size < (s32)sizeof(LOG_RECORD))
				    || (size > (s32)RH_REPLAY_MAX_ACTION_SIZE)
				    || (size & 7)) {
					printf("** Bad size %ld in block %ld"
						" offset 0x%x, stopping\n",
						(long)size,(long)blk,(int)k);
					stop = TRUE;
					state = T_ERR;
				} else {
					if (((u32)(k + size) <= blocksz)
					    && ((u32)(k + size) <= endoff)
					    && cnt < (int)(sizeof(poslist) /
							sizeof(poslist[0]))
					    && (!opts || !roothealth_guard_log_record(
						ctx, logr, size,
						roothealth_record_source_offset(buf, k),
						NULL))) {
						poslist[cnt++] = k;
						if (!logr->client_data_length)
							stop = TRUE;
						k += size;
						if (k >= endoff || (u32)(k
						    + LOG_RECORD_HEAD_SZ)
						    > blocksz)
							stop = TRUE;
					} else {
						stop = TRUE;
						state = T_ERR;
					}
				}
			}
		} else {
			stop = TRUE;
			state = (k ? T_OK : T_ERR);
		}
		prior_lsn = 0;
		for (j = 0; j < cnt && state == T_OK; ++j) {
			const LOG_RECORD *checked =
				(const LOG_RECORD *)&data[poslist[j]];
			u64 checked_lsn = sle64_to_cpu(checked->this_lsn);

			if (prior_lsn && checked_lsn <= prior_lsn)
				state = T_ERR;
			prior_lsn = checked_lsn;
		}
		if (cnt && state == T_OK) {
			const LOG_RECORD *last =
				(const LOG_RECORD *)&data[poslist[cnt - 1]];
			u32 last_size = le32_to_cpu(last->client_data_length) +
				LOG_RECORD_HEAD_SZ;

			if ((u32)poslist[cnt - 1] + last_size == endoff &&
				last->this_lsn != rph->last_end_lsn)
				state = T_ERR;
		}
	      /* Now examine an overlapping record */
		if (k
		    && ((k == endoff) || !endoff)
		    && ((u32)(k + LOG_RECORD_HEAD_SZ) <= blocksz)) {
			if (nextbuf && (blk >= BASEBLKS)) {
				nextdata = nextbuf->block.data;
				state = backoverlap(ctx, blk,
						data, nextdata, k);
			}
		}
		for (j=cnt-1; (j>=0) && (state==T_OK); j--) {
			k = poslist[j];
			logr = (const LOG_RECORD*)&data[k];
			size = le32_to_cpu(logr->client_data_length)
					+ LOG_RECORD_HEAD_SZ;
			actionnum++;
			if (optv && (!optc || within_lcn_range(logr))) {
				printf("\n* log backward action %u at 0x%x"
					" size %d (next at 0x%x)\n",
					actionnum, k, size, k + size);
			}
			if ((optv | optt)
			    && (!nextbuf && (j == (cnt - 1)))) {
				printf("* This is the latest record\n");
				if (logr->this_lsn == restart.current_lsn)
					printf("   its lsn matches the global"
						" restart lsn\n");
				if (logr->this_lsn == client.client_restart_lsn)
					printf("   its lsn matches the client"
						" restart lsn\n");
				if (logr->client_data_length
				    == restart.last_lsn_data_length)
					printf("   its length matches the"
						" last record length\n");
			}
		showlogr(ctx, k, logr);
		if (optp || optu || opts)
			state = enqueue_action(ctx, logr, size, actionnum,
					roothealth_record_source_offset(buf, k));
		}
	}
	return (state);
}

static int walkback(CONTEXT *ctx, const struct BUFFER *buf, u32 blk,
			const struct BUFFER *prevbuf, u32 prevblk)
{
	const struct BUFFER *nextbuf;
	NTFS_RECORD_TYPES magic;
	u32 stopblk;
	TRISTATE state;
	u64 steps = 0;
	u64 max_steps = (logfilesz >> blockbits) + BASEBLKS2 + 2;

	if (optv) {
		if ((log_major >= 2) && (buf->rnum != blk))
			printf("\n* block %d for block %d at 0x%llx\n",
					(int)buf->rnum,(int)blk,
					(long long)loclogblk(ctx, buf->rnum));
		else
			printf("\n* block %d at 0x%llx\n",(int)blk,
					(long long)loclogblk(ctx, blk));
	}
	ctx->firstaction = (struct ACTION_RECORD*)NULL;
	ctx->lastaction = (struct ACTION_RECORD*)NULL;
	nextbuf = (const struct BUFFER*)NULL;
	stopblk = prevblk + 2; // wraparound !
	state = backward_rcrd(ctx, blk, 0, buf,
			prevbuf, (struct BUFFER*)NULL);
	while ((state == T_OK)
	   && !((blk > stopblk) && (prevblk <= stopblk))
	   && (!(optp || optu) || (playedactions < playcount))) {
		int skipped;

		if (++steps > max_steps) {
			fprintf(stderr, "** Cyclic $LogFile block chain refused\n");
			state = T_ERR;
			break;
		}

		nextbuf = buf;
		buf = prevbuf;
		blk = prevblk;
		skipped = 0;
		prevbuf = findprevious(ctx, buf);
		if (prevbuf) {
			prevblk = prevbuf->num;
			if (prevblk < blk)
				skipped = blk - prevblk - 1;
			else
				skipped = blk - prevblk - 1
					+ (logfilesz >> blockbits)
					- (log_major < 2 ? BASEBLKS
							: BASEBLKS2);
			magic = prevbuf->block.record.magic;
			switch (magic) {
			case magic_RCRD :
				break;
			case magic_CHKD :
				printf("** Unexpected block type CHKD\n");
				break;
			case magic_RSTR :
				printf("** Unexpected block type RSTR\n");
				break;
			default :
				printf("** Invalid block %d\n",(int)prevblk);
				break;
			}
			if (optv) {
				if (skipped)
					printf("\n* block %ld at 0x%llx (block"
						" %ld used as previous one)\n",
						(long)blk,
						(long long)loclogblk(ctx, blk),
						(long)prevblk);
				else
					if ((log_major >= 2)
					    && (buf->rnum != blk))
						printf("\n* block %ld for block %ld at 0x%llx\n",
							(long)buf->rnum,
							(long)blk,
							(long long)loclogblk(
							    ctx,buf->rnum));
					else
						printf("\n* block %ld at 0x%llx\n",
							(long)blk,
							(long long)loclogblk(
								ctx, blk));
			}
			state = backward_rcrd(ctx, blk, skipped,
						buf, prevbuf, nextbuf);
		} else {
			fprintf(stderr,"** Could not read block %lu\n",
								(long)prevblk);
			state = T_ERR;
		}
	}
	if ((blk > stopblk) && (prevblk <= stopblk))
		printf("* Earliest block reached\n");
	if ((optp || optu) && (playedactions >= playcount))
		printf("* Transaction set count reached\n");
	if (opts)
		printf("* %s %s after playing %u actions\n",
				(optn ? "Sync simulation" : "Syncing"),
				(state == T_ERR ? "failed" : "successful"),
				redocount);
			/* free queue */
	while (ctx->firstaction) {
		struct ACTION_RECORD *action;

		action = ctx->firstaction->next;
		free(ctx->firstaction);
		ctx->firstaction = action;
		}
	ctx->lastaction = (struct ACTION_RECORD*)NULL;
	return (state == T_ERR ? 1 : 0);
}

/*
 *		Find the latest log block
 *
 *	Usually, the latest block is either block 2 or 3 which act as
 *	temporary block before being copied to target location.
 *	However under some unknown condition the block are written
 *	immediately to target location, and we have to scan for the
 *	latest one.
 *	Currently this is not checked for logfile version 2.x which
 *	use a different layout of temporary blocks.
 */

static const struct BUFFER *find_latest_block(CONTEXT *ctx, u32 baseblk,
			const struct BUFFER *basebuf)
{
	le64 offset;
	leLSN prevlsn;
	leLSN curlsn;
	u32 curblk;
	u32 prevblk;
	const struct BUFFER *prevbuf;
	const struct BUFFER *curbuf;

	offset = basebuf->block.record.copy.file_offset;
	curbuf = (const struct BUFFER*)NULL;
	curlsn = const_cpu_to_le64(0);
	prevblk = 0;
	curblk = baseblk;
	do {
		if (curblk < BASEBLKS) {
			prevbuf = basebuf;
			prevlsn = basebuf->block.record.last_end_lsn;
			prevblk = baseblk;
			curblk = le64_to_cpu(offset) >> blockbits;
		} else {
			if (optv)
				printf("block %d is more recent than block %d\n",
					(int)curblk, (int)prevblk);
			prevbuf = curbuf;
			prevlsn = curlsn;
			prevblk = curblk;
			curblk++;
			if (curblk >= (logfilesz >> blockbits))
				curblk = (log_major < 2 ? BASEBLKS : BASEBLKS2);
		}
		curbuf = read_buffer(ctx, curblk);
		if (curbuf && (curbuf->block.record.magic == magic_RCRD)) {
			curlsn = curbuf->block.record.copy.last_lsn;
		}
	} while (curbuf
		&& (curbuf->block.record.magic == magic_RCRD)
		&& (le64_to_cpu(curlsn) > le64_to_cpu(prevlsn)));
	if (optv)
		printf("Block %d is the latest one\n",(int)prevblk);
	return (prevbuf);
}

/*
 *		Determine the sequencing of blocks (when version >= 2.0)
 *
 *	Blocks 2..17 and 18..33 are temporary blocks being filled until
 *	they are copied to their target locations, so there are three
 *	possible location for recent blocks.
 *
 *	Returns the latest target block number
 */

struct roothealth_v2_page_meta {
	unsigned char present;
	u16 count;
	u16 position;
	u32 flags;
	u32 file_offset;
	u64 header_lsn;
	u64 last_end_lsn;
};

struct roothealth_v2_candidate {
	u32 source;
	u32 target;
	u16 count;
};

static int roothealth_v2_lsn_location(u64 lsn, u32 *page, u16 *offset)
{
	u32 sequence_bits = le32_to_cpu(restart.seq_number_bits);
	u32 offset_bits;
	u64 mask;
	u64 byte_offset;

	if (!lsn || !sequence_bits || sequence_bits >= 64U)
		return -1;
	offset_bits = 64U - sequence_bits;
	mask = (((u64)1) << offset_bits) - 1U;
	if (!(lsn & ~mask))
		return -1;
	byte_offset = (lsn & mask) << 3;
	if (byte_offset >= logfilesz ||
		(byte_offset >> blockbits) < ROOTHEALTH_V2_FIRST_PAGE ||
		(byte_offset & (blocksz - 1U)) < 0x40U)
		return -1;
	if (page)
		*page = (u32)(byte_offset >> blockbits);
	if (offset)
		*offset = (u16)(byte_offset & (blocksz - 1U));
	return 0;
}

static int roothealth_v2_pages_equivalent(CONTEXT *ctx, u32 left, u32 right)
{
	const struct BUFFER *left_buffer;
	const struct BUFFER *right_buffer;

	left_buffer = read_buffer(ctx, left);
	right_buffer = read_buffer(ctx, right);
	if (!left_buffer || !right_buffer ||
		left_buffer->block.record.magic != magic_RCRD ||
		right_buffer->block.record.magic != magic_RCRD)
		return 0;
	return !memcmp(left_buffer->block.data, right_buffer->block.data, 40U) &&
		!memcmp(left_buffer->block.data + 64U,
			right_buffer->block.data + 64U, blocksz - 64U);
}

static int roothealth_v2_candidate_compare(
		const struct roothealth_v2_candidate *left,
		const struct roothealth_v2_candidate *right,
		const struct roothealth_v2_page_meta *meta)
{
	int greater = 0;
	int less = 0;
	u16 i;

	if (left->target != right->target || left->count != right->count)
		return 2;
	for (i = 0; i < left->count; ++i) {
		u64 a = meta[left->source + i].last_end_lsn;
		u64 b = meta[right->source + i].last_end_lsn;

		greater |= a > b;
		less |= a < b;
	}
	if (greater && less)
		return 2;
	return greater ? 1 : (less ? -1 : 0);
}

static int block_sequence(CONTEXT *ctx)
{
	struct roothealth_v2_page_meta *meta = NULL;
	struct roothealth_v2_candidate candidates[BASEBLKS2 - RSTBLKS];
	int *owner = NULL;
	u32 total_pages = logfilesz >> blockbits;
	u32 candidate_count = 0;
	u32 page;
	u32 final_page = 0;
	u64 final_lsn = 0;
	u64 restart_current = sle64_to_cpu(restart.current_lsn);
	int result = 0;
	unsigned int bank;

	if (log_major != 2 || le16_to_cpu(log_header.minor_ver) != 0U ||
		total_pages <= ROOTHEALTH_V2_FIRST_PAGE)
		return 0;
	meta = (struct roothealth_v2_page_meta *)calloc(total_pages,
		sizeof(*meta));
	owner = (int *)malloc(total_pages * sizeof(*owner));
	if (!meta || !owner)
		goto out;
	for (page = 0; page < total_pages; ++page)
		owner[page] = -1;
	for (page = RSTBLKS; page < total_pages; ++page) {
		const struct BUFFER *buffer = read_buffer(ctx, page);
		const RECORD_PAGE_HEADER *header;

		if (!buffer)
			goto malformed;
		if (!~buffer->block.record.magic)
			continue;
		if (buffer->block.record.magic != magic_RCRD)
			goto malformed;
		header = &buffer->block.record;
		meta[page].present = 1;
		meta[page].count = le16_to_cpu(header->page_count);
		meta[page].position = le16_to_cpu(header->page_position);
		meta[page].flags = le32_to_cpu(header->flags);
		meta[page].file_offset = getle32(buffer->block.data, 60U);
		meta[page].header_lsn = sle64_to_cpu(header->copy.last_lsn);
		meta[page].last_end_lsn = sle64_to_cpu(header->last_end_lsn);
		if (roothealth_v2_lsn_location(meta[page].header_lsn,
				NULL, NULL) ||
			(meta[page].last_end_lsn && roothealth_v2_lsn_location(
				meta[page].last_end_lsn, NULL, NULL)))
			goto malformed;
		if (page >= ROOTHEALTH_V2_FIRST_PAGE && meta[page].file_offset) {
			goto malformed;
		}
	}

	/* Each of the two v2 tail banks contains one bounded atomic transfer. */
	for (bank = 0; bank < 2U; ++bank) {
		u32 first = RSTBLKS + bank * RH_REPLAY_MAX_IO_PAGES;
		u32 limit = first + RH_REPLAY_MAX_IO_PAGES;

		for (page = first; page < limit; ++page) {
			struct roothealth_v2_candidate *candidate;
			u32 target;
			u16 count;
			u16 i;
			int complete = 1;

			if (!meta[page].present || meta[page].position != 1U)
				continue;
			count = meta[page].count;
			if (!count || page + count > limit)
				goto malformed;
			target = meta[page].file_offset >> blockbits;
			for (i = 0; i < count; ++i) {
				u32 expected = target + i;

				if (expected >= total_pages)
					expected = ROOTHEALTH_V2_FIRST_PAGE +
						(expected - total_pages);
				if (!meta[page + i].present ||
					meta[page + i].count != count ||
					meta[page + i].position != i + 1U ||
					(meta[page + i].file_offset >> blockbits) != expected) {
					complete = 0;
					break;
				}
				if (i && meta[page + i].last_end_lsn <
						meta[page + i - 1U].last_end_lsn)
					goto malformed;
			}
			if (!complete)
				continue;
			if (candidate_count >= sizeof(candidates) / sizeof(candidates[0]))
				goto malformed;
			candidate = &candidates[candidate_count++];
			candidate->source = page;
			candidate->target = target;
			candidate->count = count;
			page += count - 1U;
		}
	}

	for (page = 0; page < candidate_count; ++page) {
		const struct roothealth_v2_candidate *candidate = &candidates[page];
		int greater = 0;
		int less = 0;
		int existing = -1;
		u16 i;

		for (i = 0; i < candidate->count; ++i) {
			u32 target = candidate->target + i;
			u64 source_lsn = meta[candidate->source + i].last_end_lsn;
			u64 target_lsn;

			if (target >= total_pages)
				target = ROOTHEALTH_V2_FIRST_PAGE +
					(target - total_pages);
			target_lsn = meta[target].present ? meta[target].last_end_lsn : 0;
			greater |= source_lsn > target_lsn;
			less |= source_lsn < target_lsn;
		}
		if (greater && less)
			goto malformed;
		if (!greater) {
			if (!less) {
				for (i = 0; i < candidate->count; ++i) {
					u32 target = candidate->target + i;

					if (target >= total_pages)
						target = ROOTHEALTH_V2_FIRST_PAGE +
							(target - total_pages);
					if (!meta[target].present ||
						!roothealth_v2_pages_equivalent(ctx,
							candidate->source + i, target))
						goto malformed;
				}
			}
			continue;
		}
		for (i = 0; i < candidate->count; ++i) {
			u32 target = candidate->target + i;

			if (target >= total_pages)
				target = ROOTHEALTH_V2_FIRST_PAGE +
					(target - total_pages);
			if (owner[target] >= 0) {
				if (existing < 0)
					existing = owner[target];
				else if (existing != owner[target])
					goto malformed;
			}
		}
		if (existing >= 0) {
			int compare = roothealth_v2_candidate_compare(candidate,
				&candidates[existing], meta);

			if (compare == 2)
				goto malformed;
			if (compare < 0)
				continue;
			if (!compare) {
				for (i = 0; i < candidate->count; ++i)
					if (!roothealth_v2_pages_equivalent(ctx,
						candidate->source + i,
						candidates[existing].source + i))
						goto malformed;
				continue;
			}
			for (i = 0; i < candidates[existing].count; ++i) {
				u32 target = candidates[existing].target + i;

				if (target >= total_pages)
					target = ROOTHEALTH_V2_FIRST_PAGE +
						(target - total_pages);
				owner[target] = -1;
			}
		}
		for (i = 0; i < candidate->count; ++i) {
			u32 target = candidate->target + i;

			if (target >= total_pages)
				target = ROOTHEALTH_V2_FIRST_PAGE +
					(target - total_pages);
			if (owner[target] >= 0)
				goto malformed;
			owner[target] = (int)page;
		}
	}

	for (page = ROOTHEALTH_V2_FIRST_PAGE; page < total_pages; ++page) {
		const struct roothealth_v2_page_meta *selected;
		u32 source = page;

		if (owner[page] >= 0) {
			const struct roothealth_v2_candidate *candidate =
				&candidates[owner[page]];
			u32 delta = page >= candidate->target ? page - candidate->target :
				total_pages - candidate->target +
					page - ROOTHEALTH_V2_FIRST_PAGE;

			if (delta >= candidate->count)
				goto malformed;
			source = candidate->source + delta;
			redirect[source] = page;
		}
		selected = &meta[source];
		if (!selected->present || !(selected->flags & 1U) ||
			!selected->last_end_lsn)
			continue;
		if (selected->last_end_lsn > final_lsn) {
			final_lsn = selected->last_end_lsn;
			final_page = page;
		}
	}
	if (!final_lsn || final_lsn < restart_current ||
		roothealth_v2_lsn_location(final_lsn, &page, NULL) ||
		page != final_page)
		goto malformed;
	latest_lsn = final_lsn;
	result = (int)final_page;
	if (optv > 1)
		printf("v2 final lsn %llx in logical block %u\n",
			(long long)final_lsn, final_page);
	goto out;

malformed:
	++rh_parse_errors;
	memset(redirect, 0, sizeof(redirect));
out:
	free(owner);
	free(meta);
	return result;
}

static int walk(CONTEXT *ctx)
{
	const struct BUFFER *buf;
	const struct BUFFER *nextbuf;
	const struct BUFFER *prevbuf;
	const struct BUFFER *startbuf;
	const NTFS_RECORD *record;
	const RECORD_PAGE_HEADER *rph;
	NTFS_RECORD_TYPES magic;
	u32 blk;
	u32 nextblk;
	u32 prevblk;
	u32 finalblk;
	int err;
	u16 blkheadsz;
	u16 pos;
	BOOL dirty;
	BOOL done;
	u64 steps;
	u64 max_steps;

	buf = (struct BUFFER*)NULL;
	nextbuf = (struct BUFFER*)NULL;
	if (optb || optp || optu || opts) {
		prevbuf = (struct BUFFER*)NULL;
	}
	done = FALSE;
	dirty = TRUE;
	finalblk = 0;
	err = 0;
	blk = 0;
	pos = 0;
	steps = 0;
	max_steps = (logfilesz >> BLOCKBITS) + BASEBLKS2 + 4;
			/* read and process the first restart block */
	buf = read_restart(ctx);
	if (buf) {
		/*
		 * A selected, release-profile restart page carrying the clean flag is
		 * the authoritative LFS shutdown verdict.  Its old record pages are
		 * historical data, not recovery work.  Walking those pages can reject
		 * otherwise clean Windows volumes merely because an obsolete operation
		 * lies outside RootHealth's bounded replay surface.
		 */
		if (restart.flags & RESTART_VOLUME_IS_CLEAN) {
			rh_log_needs_replay = FALSE;
			return 0;
		}
		if (!restart_lsn && !synced_lsn && !committed_lsn &&
			!sle64_to_cpu(client.oldest_lsn) &&
			!sle64_to_cpu(client.client_restart_lsn)) {
			rh_log_needs_replay =
				!(restart.flags & RESTART_VOLUME_IS_CLEAN);
			return 0;
		}
		if (optv)
			printf("\n* block %d at 0x%llx\n",(int)blk,
					(long long)loclogblk(ctx, blk));
	} else {
		done = TRUE;
		err = 1;
	}

	nextblk = blk + 1;
	while (!done) {
		if (++steps > max_steps) {
			fprintf(stderr, "** Cyclic or oversized $LogFile walk refused\n");
			err = 1;
			break;
		}
		 /* next block is needed to process the current one */
		if ((nextblk >= (logfilesz >> blockbits)) && (optr || optf))
			nextbuf = read_buffer(ctx,
					(log_major < 2 ? BASEBLKS : BASEBLKS2));
		else
			nextbuf = read_buffer(ctx,nextblk);
		if (nextbuf) {
			record = (const NTFS_RECORD*)&nextbuf->block.data;
			blkheadsz = nextbuf->headsz;
			magic = record->magic;
			switch (magic) {
			case magic_CHKD :
				fprintf(stderr,
					"** Obsoleted alternate restart page\n");
				err = 1;
				done = TRUE;
				break;
			case magic_RSTR :
				if (!roothealth_restart_profile_valid(
						&nextbuf->block.restart)) {
					fprintf(stderr,
						"** Invalid alternate restart page\n");
					err = 1;
					done = TRUE;
				}
				break;
			case magic_RCRD :
				break;
			default :
				printf("** Invalid block\n");
				err = 1;
				break;
			}
			magic = buf->block.record.magic;
			switch (magic) {
			case magic_CHKD :
			case magic_RSTR :
				dirty = dorest(ctx, blk, &buf->block.restart,
								FALSE);
				rh_log_needs_replay = dirty;
				break;
			case magic_RCRD :
				if (blk < BASEBLKS)
					pos = buf->headsz;
				pos = dorcrd(ctx, blk, pos, buf, nextbuf);
				while (pos >= blocksz) {
					if (optv > 1)
						printf("Skipping block %d"
						" pos 0x%x\n",
						(int)nextblk,(int)pos);
					pos -= (blocksz - blkheadsz);
					nextblk++;
					}
				if ((blocksz - pos) < LOG_RECORD_HEAD_SZ) {
					pos = 0;
					nextblk++;
				}
				if (nextblk != (blk + 1)) {
					nextbuf = read_buffer(ctx,nextblk);
				}
				break;
			default :
				if (!~magic) {
					if (optv)
						printf("   empty block\n");
				}
				break;
			}
		} else {
			fprintf(stderr,"* Could not read block %d\n",nextblk);
			if (ctx->vol) {
			/* In full mode, ignore errors on restart blocks */
				if (blk >= RSTBLKS) {
					done = TRUE;
					err = 1;
				}
			} else {
				done = TRUE;
				err = 1;
			}
		}
		blk = nextblk;
		nextblk++;

		if (!optr && (log_major >= 2) && (nextblk == RSTBLKS)) {
			finalblk = block_sequence(ctx);
			if (!finalblk) {
				done = TRUE;
				err = 1;
			}
		}

		if (optr) { /* Only selected range */
			u32 endblk;

			endblk = (log_major < 2 ? BASEBLKS : RSTBLKS);
			if ((nextblk == endblk) && (nextblk < firstblk))
				 nextblk = firstblk;
			if ((blk >= endblk) && (blk > lastblk))
				done = TRUE;
		} else
			if (optf) { /* Full log, forward */
				if (blk*blocksz >= logfilesz)
					done = TRUE;
			} else
				if (optb || optp || optu || opts
				    || (log_major >= 2)) {
					/* Restart blocks only (2 blocks) */
					if (blk >= RSTBLKS)
						done = TRUE;
				} else { /* Base blocks only (4 blocks) */
					if (blk >= BASEBLKS)
						done = TRUE;
				}
		if (!done) {
			buf = nextbuf;
			if (blk >= RSTBLKS && blk < BASEBLKS) {
				/* The latest buf may be more recent
				   than restart */
				rph = &buf->block.record;
				if ((s64)(sle64_to_cpu(rph->last_end_lsn)
					  - committed_lsn) > 0) {
					committed_lsn =
						sle64_to_cpu(rph->last_end_lsn);
					if (optv)
						printf("* Restart page was "
						       "obsolete, updated "
						       "committed lsn\n");
				}
			}
			if (optv)
				printf("\n* block %d at 0x%llx\n",(int)blk,
					(long long)loclogblk(ctx, blk));
		}
	}
	if (optv && opts && !dirty)
		printf("* Volume is clean, nothing to do\n");
	if (log_major >= 2)
		blk = finalblk;
	if (!err
	    && (optb || optp || optu || (opts && dirty))) {
		playedactions = 0;
		ctx->firstaction = (struct ACTION_RECORD*)NULL;
		ctx->lastaction = (struct ACTION_RECORD*)NULL;
		if (log_major < 2) {
			buf = nextbuf;
			nextbuf = read_buffer(ctx, blk+1);
			startbuf = best_start(buf,nextbuf);
			if (startbuf && (startbuf == nextbuf)) {
				/* nextbuf is better, show blk */
				if (optv && buf) {
					printf("* Ignored block %d at 0x%llx\n",
						(int)blk,
						(long long)loclogblk(ctx, blk));
					if (optv >= 2)
						hexdump(buf->block.data,
								blocksz);
					showheadrcrd(blk, &buf->block.record);
				}
				blk++;
				buf = nextbuf;
			} else {
				/* buf is better, show blk + 1 */
				if (optv && nextbuf) {
					printf("* Ignored block %d at 0x%llx\n",
						(int)(blk + 1),
						(long long)loclogblk(ctx,
								blk + 1));
					if (optv >= 2)
						hexdump(nextbuf->block.data,
								blocksz);
					showheadrcrd(blk + 1,
							&nextbuf->block.record);
				}
			}
			if (startbuf && opts) {
				buf = startbuf = find_latest_block(ctx,
						blk, startbuf);
				latest_lsn = le64_to_cpu(
					buf->block.record.last_end_lsn);
			}
		} else {
			buf = startbuf = read_buffer(ctx, blk);
			nextbuf = (const struct BUFFER*)NULL;
		}
		if (startbuf) {
			/* The latest buf may be more recent than restart */
			rph = &buf->block.record;
			if ((s64)(sle64_to_cpu(rph->last_end_lsn)
					- committed_lsn) > 0) {
				committed_lsn = sle64_to_cpu(rph->last_end_lsn);
				if (optv)
					printf("* Restart page was obsolete\n");
			}
			nextbuf = (const struct BUFFER*)NULL;
			prevbuf = findprevious(ctx, buf);
			if (prevbuf) {
				prevblk = prevbuf->num;
				magic = prevbuf->block.record.magic;
				switch (magic) {
				case magic_RCRD :
					break;
				case magic_CHKD :
					printf("** Unexpected block type CHKD\n");
					err = 1;
					break;
				case magic_RSTR :
					err = 1;
					printf("** Unexpected block type RSTR\n");
					break;
				default :
					err = 1;
					printf("** Invalid block\n");
					break;
				}
			} else
				prevblk = BASEBLKS;
			if (!err)
				err = walkback(ctx, buf, blk,
							prevbuf, prevblk);
		} else {
			fprintf(stderr,"** No valid start block, aborting\n");
			err = 1;
		}
	}
	return (err);
}

BOOL exception(int num)
{
	int i;

	i = 0;
	while ((i < 10) && optx[i] && (optx[i] != num))
		i++;
	return (optx[i] == num);
}

static void version(void)
{
	printf("\n%s v%s (libntfs-3g) - Recover updates committed by Windows"
			" on an NTFS Volume.\n\n", "ntfsrecover", VERSION);
	printf("Copyright (c) 2012-2017 Jean-Pierre Andre\n");
	printf("\n%s\n%s%s\n", ntfs_gpl, ntfs_bugs, ntfs_home);
}

static void usage(void)
{
	fprintf(stderr,"Usage : for recovering the updates committed by Windows :\n");
	fprintf(stderr,"        ntfsrecover partition\n");
	fprintf(stderr,"                (e.g. ntfsrecover /dev/sda1)\n");
	fprintf(stderr,"Advanced : ntfsrecover [-b] [-c first-last] [-i] [-f] [-n] [-p count]\n");
	fprintf(stderr,"                    [-r first-last] [-t] [-u count] [-v] partition\n");
	fprintf(stderr,"	   -b : show the full log backward\n");
	fprintf(stderr,"	   -c : restrict to the actions related to cluster range\n");
	fprintf(stderr,"	   -i : show invalid (stale) records\n");
	fprintf(stderr,"	   -f : show the full log forward\n");
	fprintf(stderr,"	   -h : show this help information\n");
	fprintf(stderr,"	   -k : kill fast restart data\n");
	fprintf(stderr,"	   -n : do not apply any modification\n");
	fprintf(stderr,"	   -p : undo the latest count transaction sets and play one\n");
	fprintf(stderr,"	   -r : show a range of log blocks forward\n");
	fprintf(stderr,"	   -s : sync the committed changes (default)\n");
	fprintf(stderr,"	   -t : show transactions\n");
	fprintf(stderr,"	   -u : undo the latest count transaction sets\n");
	fprintf(stderr,"	   -v : show more information (-vv yet more)\n");
	fprintf(stderr,"	   -V : show version and exit\n");
}

/*
 *		Process command options
 */

static BOOL __attribute__((unused)) getoptions(int argc, char *argv[])
{
	int c;
	int xcount;
	u32 xval;
	char *endptr;
	BOOL err;
	static const char *sopt = "-bc:hifknp:r:stu:vVx:";
	static const struct option lopt[] = {
		{ "backward",		no_argument,		NULL, 'b' },
		{ "clusters",		required_argument,	NULL, 'c' },
		{ "forward",		no_argument,		NULL, 'f' },
		{ "help",		no_argument,		NULL, 'h' },
		{ "kill-fast-restart",	no_argument,		NULL, 'k' },
		{ "no-action",		no_argument,		NULL, 'n' },
		{ "play",		required_argument,	NULL, 'p' },
		{ "range",		required_argument,	NULL, 'r' },
		{ "sync",		no_argument,		NULL, 's' },
		{ "transactions",	no_argument,		NULL, 't' },
		{ "undo",		required_argument,	NULL, 'u' },
		{ "verbose",		no_argument,		NULL, 'v' },
		{ "version",		no_argument,		NULL, 'V' },
		{ "exceptions",		required_argument,	NULL, 'x' },
		{ NULL, 		0, NULL, 0 }
	};

	err = FALSE;
	optb = FALSE;
	optc = FALSE;
	optd = FALSE;
	optf = FALSE;
	opth = FALSE;
	opti = FALSE;
	optk = FALSE;
	optn = FALSE;
	optp = FALSE;
	optr = FALSE;
	opts = 0;
	optt = FALSE;
	optu = FALSE;
	optv = 0;
	optV = FALSE;
	optx[0] = 0;

	while ((c = getopt_long(argc, argv, sopt, lopt, NULL)) != -1) {
		switch (c) {
		case 1:	/* A non-option argument */
			if (optind == argc)
				optd = TRUE;
			else {
				fprintf(stderr, "Device must be the"
						" last argument.\n");
				err = TRUE;
			}
			break;
		case 'b':
			optb = TRUE;
			break;
		case 'c':
			firstlcn = strtoull(optarg, &endptr, 0);
			lastlcn = firstlcn;
			if (*endptr == '-')
				lastlcn = strtoull(++endptr, &endptr, 0);
			if (*endptr || (lastlcn < firstlcn)) {
				fprintf(stderr,"Bad cluster range\n");
				err = TRUE;
			} else
				optc = TRUE;
			break;
		case 'f':
			optf = TRUE;
			break;
		case '?':
		case 'h':
			opth = TRUE;
			break;
		case 'k':
			optk = TRUE;
			break;
		case 'n':
			optn = TRUE;
			break;
		case 'p':
			playcount = strtoull(optarg, &endptr, 0);
			if (*endptr) {
				fprintf(stderr,"Bad play count\n");
				err = TRUE;
			} else
				optp = TRUE;
			break;
		case 'r' :
			firstblk = strtoull(optarg, &endptr, 0);
			lastblk = firstblk;
			if (*endptr == '-')
				lastblk = strtoull(++endptr, &endptr, 0);
			if (*endptr || (lastblk < firstblk)) {
				fprintf(stderr,"Bad log block range\n");
				err = TRUE;
			} else
				optr = TRUE;
			break;
		case 's':
			opts++;
			break;
		case 't':
			optt = TRUE;
			break;
		case 'u':
			playcount = strtoull(optarg, &endptr, 0);
			if (*endptr) {
				fprintf(stderr,"Bad undo count\n");
				err = TRUE;
			} else
				optu = TRUE;
			break;
		case 'v':
			optv++;
			break;
		case 'V':
			optV = TRUE;
			break;
		case 'x':
				/*
				 * Undocumented : actions to execute, though
				 * they should be skipped under normal rules.
				 */
			xcount = 0;
			xval = strtoull(optarg, &endptr, 0);
			while ((*endptr == ',')
			    && (xcount < (MAXEXCEPTION - 1))) {
				optx[xcount++] = xval;
				xval = strtoull(++endptr, &endptr, 0);
			}
			if (*endptr || (xcount >= MAXEXCEPTION)) {
				fprintf(stderr,"Bad exception list\n");
				err = TRUE;
			} else {
				optx[xcount++] = xval;
				optx[xcount] = 0;
			}
			break;
		default:
			fprintf(stderr,"Unknown option '%s'.\n",
							argv[optind - 1]);
			err = TRUE;
		}
	}

	if (!optd && !optV && !opth) {
		fprintf(stderr,"Device argument is missing\n");
		err = TRUE;
	}
	if (!(optb || optf || optp || optr || opts || optt || optu || optV))
		opts = 1;
	if (optb && (optf || optr || opts)) {
		fprintf(stderr,"Options -f, -r and -s are incompatible with -b\n");
		err = TRUE;
	}
	if (optf && (optp || opts || optu)) {
		fprintf(stderr,"Options -p, -s and -u are incompatible with -f\n");
		err = TRUE;
	}
	if (optp && (optr || opts || optt || optu)) {
		fprintf(stderr,"Options -r, -s, -t and -u are incompatible with -p\n");
		err = TRUE;
	}
	if (optr && (opts || optu)) {
		fprintf(stderr,"Options -s and -u are incompatible with -r\n");
		err = TRUE;
	}
	if (opts && (optt || optu)) {
		fprintf(stderr,"Options -t and -u are incompatible with -s\n");
		err = TRUE;
	}

	if (opth || err)
		usage();
	else
		if (optV)
			version();
	return (!err);
}

/*
 *		Quick checks on the layout of needed structs
 */

static BOOL checkstructs(void)
{
	BOOL ok;

	ok = TRUE;
	if (sizeof(RECORD_PAGE_HEADER) != 40) {
		fprintf(stderr,
			"* error : bad sizeof(RECORD_PAGE_HEADER) %d\n",
			(int)sizeof(RECORD_PAGE_HEADER));
		ok = FALSE;
	}
	if (sizeof(LOG_RECORD) != 88) {
		fprintf(stderr,
			"* error : bad sizeof(LOG_RECORD) %d\n",
			(int)sizeof(LOG_RECORD));
		ok = FALSE;
	}
	if (sizeof(RESTART_PAGE_HEADER) != 32) {
		fprintf(stderr,
			"* error : bad sizeof(RESTART_PAGE_HEADER) %d\n",
			(int)sizeof(RESTART_PAGE_HEADER));
		ok = FALSE;
	}
	if (sizeof(RESTART_AREA) != 48) {
		fprintf(stderr,
			"* error : bad sizeof(RESTART_AREA) %d\n",
			(int)sizeof(RESTART_AREA));
		ok = FALSE;
	}
	if (sizeof(ATTR_OLD) != 44) {
		fprintf(stderr,
			"* error : bad sizeof(ATTR_OLD) %d\n",
			(int)sizeof(ATTR_OLD));
		ok = FALSE;
	}
	if (sizeof(ATTR_NEW) != 40) {
		fprintf(stderr,
			"* error : bad sizeof(ATTR_NEW) %d\n",
			(int)sizeof(ATTR_NEW));
		ok = FALSE;
	}
	if (LastAction != 38) {
		fprintf(stderr,
			"* error : bad action list, %d actions\n",
			(int)LastAction);
		ok = FALSE;
	}
	return (ok);
}

static int roothealth_logfile_is_wiped(void)
{
	unsigned char *page;
	u64 offset;
	int result = 1;

	if (!log_na || logfilesz < RH_REPLAY_MIN_LOGFILE_SIZE ||
		logfilesz > RH_REPLAY_MAX_LOGFILE_SIZE ||
		log_na->data_size != logfilesz)
		return -1;
	page = (unsigned char *)malloc(RH_REPLAY_PAGE_SIZE);
	if (!page)
		return -1;
	for (offset = 0; offset < logfilesz; offset += RH_REPLAY_PAGE_SIZE) {
		size_t i;

		if (ntfs_attr_pread(log_na, offset, RH_REPLAY_PAGE_SIZE, page) !=
				RH_REPLAY_PAGE_SIZE) {
			errno = EIO;
			++rh_io_errors;
			result = -1;
			break;
		}
		roothealth_note_log_page((unsigned int)(offset / RH_REPLAY_PAGE_SIZE));
		++rh_wiped_pages_scanned;
		for (i = 0; i < RH_REPLAY_PAGE_SIZE; ++i)
			if (page[i] != 0xffU) {
				result = 0;
				break;
			}
		if (!result)
			break;
	}
	free(page);
	return result;
}

static int roothealth_log_replay_plan_common(const char *device_name,
		struct rh_writer *writer,
		const struct rh_replay_slot_authority_provider *provider,
		struct rh_log_result *result, ntfs_volume *mounted_volume,
		size_t checkpoint)
{
	CONTEXT ctx;
	unsigned int i;
	u64 planned_bytes_before;
	int err;
	int saved_errno;

	if (!result) {
		errno = EINVAL;
		return -1;
	}
	memset(result, 0, sizeof(*result));
	roothealth_reset_log_evidence();
	/*
	 * The provisional InitializeFileRecordSegment provider only returns a
	 * transient pre-transaction approval.  Until the outer raw-MFT/bitmap/
	 * namespace seal, post-overlay hash, and WAL recovery verifier ABI are
	 * frozen together, allowing that callback to authorize an ID5 operation
	 * would create evidence which recovery cannot rederive.  Keep this entry
	 * point explicitly unreachable; exact already-applied Initialize records
	 * may still be recognized as zero-write endpoints by the provider-free
	 * parser and remain subject to the outer full-overlay checker.
	 */
	if (provider) {
		errno = EOPNOTSUPP;
		return -1;
	}
	if (!device_name || !writer || !writer->path ||
		strcmp(device_name, writer->path) || writer->read_fd < 0 ||
		writer->write_fd >= 0 || checkpoint > writer->operation_count ||
		(!mounted_volume && checkpoint) ||
		(!mounted_volume && (writer->operation_count || writer->planned_bytes)) ||
		writer->commit_started || writer->commit_completed ||
		(provider && (provider->version !=
			RH_REPLAY_SLOT_AUTHORITY_PROVIDER_VERSION ||
			provider->reserved32 || !provider->expected_volume_serial ||
			!provider->authorize_initialize))) {
		errno = EINVAL;
		return -1;
	}
	planned_bytes_before = writer->planned_bytes;
	memset(&ctx, 0, sizeof(ctx));
	memset(&log_header, 0, sizeof(log_header));
	memset(&restart, 0, sizeof(restart));
	memset(&client, 0, sizeof(client));
	log_ni = NULL;
	log_na = NULL;
	log_major = 0;
	logfilesz = 0;
	committed_lsn = 0;
	synced_lsn = 0;
	latest_lsn = 0;
	restart_lsn = 0;
	err = 1;
	if (checkstructs()) {
			/* Fixed qualification policy; analysis selects winner redo/loser undo. */
			optb = FALSE;
			optc = FALSE;
			optd = TRUE;
			opth = FALSE;
			opti = FALSE;
			optf = FALSE;
			optk = FALSE;
			optn = TRUE;
			optp = FALSE;
			optr = FALSE;
			opts = 1;
			optt = FALSE;
			optu = FALSE;
			optv = 0;
			optV = FALSE;
			memset(optx, 0, sizeof(optx));
			redocount = 0;
			undocount = 0;
			actionnum = 0;
			attrcount = 0;
			redos_met = 0;
			committed_lsn = 0;
			synced_lsn = 0;
			latest_lsn = 0;
			restart_lsn = 0;
			rh_restart_pages_planned = 0;
			rh_log_needs_replay = FALSE;
			rh_replay_writer = writer;
			rh_replay_slot_authority_provider = provider;
			attrtable = (struct ATTR**)NULL;
			for (i=0; i<(BUFFERCNT + BASEBLKS); i++)
				buffer_table[i] = (struct BUFFER*)NULL;
			ntfs_log_set_handler(ntfs_log_handler_outerr);
			if (open_volume(&ctx, device_name, mounted_volume)) {
				if (ctx.vol) {
					int wiped;

					if (roothealth_prepare_log_evidence())
						err = 1;
					else {
						result->checked = 1;
						result->logfile_bytes = logfilesz;
						if (ntfs_volume_check_hiberfile(ctx.vol, 1) < 0)
							err = 1;
						else if (NVolLogFileEmpty(ctx.vol)) {
							wiped = roothealth_logfile_is_wiped();
							if (wiped > 0) {
								err = 0;
								result->state = RH_NATIVE_LOG_EMPTY_T1OS;
							} else
								err = 1;
						} else {
							wiped = roothealth_logfile_is_wiped();
							if (wiped > 0) {
								err = 0;
								result->state = RH_NATIVE_LOG_EMPTY_T1OS;
							} else if (!wiped)
								err = walk(&ctx);
							else
								err = 1;
						}
						if (!err && rh_log_needs_replay)
							err = roothealth_plan_clean_restart_pages(&ctx);
						/*
						 * RootHealth WAL v1 has one entry per typed operation.  Native
						 * recovery is one indivisible transaction, so reject an exact
						 * completed plan that cannot fit instead of exposing a prefix.
						 * All accepted targets are 512-byte aligned, making planned
						 * bytes identical to the WAL old-sector footprint.
						 */
						if (!err && rh_log_needs_replay &&
							(writer->operation_count - checkpoint >
								ROOTHEALTH_NATIVE_WAL_MAX_OPERATIONS ||
							 writer->planned_bytes - planned_bytes_before >
								ROOTHEALTH_NATIVE_WAL_MAX_TARGET_BYTES)) {
							fprintf(stderr, "** Native replay plan exceeds the "
								"atomic WAL capacity\n");
							errno = ENOSPC;
							++rh_unsupported_actions;
							err = 1;
						}
					}
					ntfs_attr_close(log_na);
					ntfs_inode_close(log_ni);
					if (!mounted_volume)
						ntfs_umount(ctx.vol, TRUE);
				} else {
					fprintf(stderr, "A complete NTFS device is required\n");
					fclose(ctx.file);
					err = 1;
				}
			} else
				fprintf(stderr,"Could not open %s\n",
							device_name);
			result->major_version = log_major;
			result->minor_version = le16_to_cpu(log_header.minor_ver);
			result->pages_expected = rh_pages_expected;
			result->pages_examined = rh_pages_examined;
			result->wiped_pages_scanned = rh_wiped_pages_scanned;
			result->restart_lsn = restart_lsn;
			result->synced_lsn = synced_lsn;
			result->committed_lsn = committed_lsn;
			result->latest_lsn = latest_lsn;
			result->actions_seen = actionnum;
			result->checkpoint_records_examined =
				rh_analysis_evidence.checkpoint_records;
			result->mutation_records_examined =
				rh_analysis_evidence.mutation_records;
			result->control_records_examined = actionnum >=
				rh_analysis_evidence.mutation_records ? actionnum -
				rh_analysis_evidence.mutation_records : 0;
			result->open_attribute_tables =
				rh_analysis_evidence.open_attribute_tables;
			result->attribute_name_tables =
				rh_analysis_evidence.attribute_name_tables;
			result->dirty_page_tables =
				rh_analysis_evidence.dirty_page_tables;
			result->transaction_tables =
				rh_analysis_evidence.transaction_tables;
			result->redo_actions = redocount;
			result->undo_actions = undocount;
			result->restart_pages_planned = rh_restart_pages_planned;
			result->unsupported_actions = rh_unsupported_actions;
			result->io_errors = rh_io_errors;
			result->parse_errors = rh_parse_errors;
			if (!err && result->state == RH_NATIVE_LOG_UNKNOWN)
				result->state = writer->operation_count > checkpoint ?
					RH_NATIVE_LOG_REPLAY_PLANNED :
					RH_NATIVE_LOG_CLEAN_RESTART;
			while (ctx.firstaction) {
				struct ACTION_RECORD *next = ctx.firstaction->next;

				free(ctx.firstaction);
				ctx.firstaction = next;
			}
			ctx.lastaction = (struct ACTION_RECORD *)NULL;
			for (i=0; i<(BUFFERCNT + BASEBLKS); i++)
				free(buffer_table[i]);
			for (i=0; i<attrcount; i++)
				free(attrtable[i]);
			free(attrtable);
			if (ctx.vol) {
				freeclusterentry((struct STORE*)NULL);
				show_redos();
			}
	}
	saved_errno = errno;
	/*
	 * A structurally valid native log whose complete atomic plan exceeds the
	 * bounded supported profile is an unsupported-format/capacity refusal,
	 * not a device I/O or allocator failure.  Preserve that distinction after
	 * cleanup so orchestration maps it to UNSAFE/exit 2 with a zero plan and
	 * an untouched WAL.
	 */
	if (err && rh_unsupported_actions && !rh_io_errors)
		saved_errno = EOPNOTSUPP;
	rh_replay_writer = NULL;
	rh_replay_slot_authority_provider = NULL;
	if (err) {
		if (!rh_io_errors && !rh_parse_errors && !rh_unsupported_actions)
			++rh_parse_errors;
		if (rh_writer_discard_after(writer, checkpoint) && !saved_errno)
			saved_errno = EIO;
		result->state = RH_NATIVE_LOG_UNKNOWN;
		result->io_errors = rh_io_errors;
		result->parse_errors = rh_parse_errors;
		result->unsupported_actions = rh_unsupported_actions;
	}
	result->planned_io_operations = writer->operation_count - checkpoint;
	result->planned_io_bytes = writer->planned_bytes - planned_bytes_before;
	free(rh_examined_pages);
	rh_examined_pages = NULL;
	errno = saved_errno;
	return err ? -1 : 0;
}

int roothealth_boot_clean_probe(const char *device_name,
		struct rh_writer *writer, struct rh_log_result *result,
		int *dirty_out)
{
	CONTEXT ctx;
	RESTART_PAGE_HEADER *selected = NULL;
	const RESTART_AREA *selected_area;
	unsigned int i;
	int clean = 0;

	if (!device_name || !writer || !writer->path || !result || !dirty_out ||
			strcmp(device_name, writer->path) || writer->read_fd < 0 ||
			writer->write_fd >= 0 || writer->operation_count ||
			writer->planned_bytes || writer->commit_started ||
			writer->commit_completed) {
		errno = EINVAL;
		return -1;
	}
	memset(result, 0, sizeof(*result));
	*dirty_out = -1;
	roothealth_reset_log_evidence();
	memset(&ctx, 0, sizeof(ctx));
	memset(&log_header, 0, sizeof(log_header));
	memset(&restart, 0, sizeof(restart));
	memset(&client, 0, sizeof(client));
	log_ni = NULL;
	log_na = NULL;
	log_major = 0;
	logfilesz = 0;
	committed_lsn = 0;
	synced_lsn = 0;
	latest_lsn = 0;
	restart_lsn = 0;
	attrtable = NULL;
	attrcount = 0;
	actionnum = 0;
	redocount = 0;
	undocount = 0;
	rh_restart_pages_planned = 0;
	rh_log_needs_replay = FALSE;
	rh_replay_writer = NULL;
	rh_replay_slot_authority_provider = NULL;
	for (i = 0; i < BUFFERCNT + BASEBLKS; ++i)
		buffer_table[i] = NULL;

	ntfs_log_set_handler(ntfs_log_handler_outerr);
	if (!open_volume(&ctx, device_name, NULL))
		goto out;
	if (logfilesz < RH_REPLAY_MIN_LOGFILE_SIZE ||
			logfilesz > RH_REPLAY_MAX_LOGFILE_SIZE ||
			(logfilesz & (RH_REPLAY_PAGE_SIZE - 1U)) ||
			ntfs_volume_check_hiberfile(ctx.vol, 1) < 0 ||
			NVolLogFileEmpty(ctx.vol))
		goto close_volume;
	*dirty_out = !!(ctx.vol->flags & VOLUME_IS_DIRTY);
	/*
	 * ntfs_check_logfile() reads and selects only the two restart pages.  Do
	 * not call walk()/read_restart() here: those initialize replay state and
	 * may inspect historical record pages which are irrelevant to clean boot.
	 */
	if (!ntfs_check_logfile(log_na, &selected) || !selected ||
			!roothealth_restart_page_supported(selected, logfilesz))
		goto close_volume;
	selected_area = (const RESTART_AREA *)((const unsigned char *)selected +
		le16_to_cpu(selected->restart_area_offset));
	if (!(selected_area->flags & RESTART_VOLUME_IS_CLEAN))
		goto close_volume;
	result->checked = 1;
	result->state = RH_NATIVE_LOG_CLEAN_RESTART;
	result->major_version = le16_to_cpu(selected->major_ver);
	result->minor_version = le16_to_cpu(selected->minor_ver);
	result->logfile_bytes = logfilesz;
	result->pages_expected = logfilesz / RH_REPLAY_PAGE_SIZE;
	result->pages_examined = 2U;
	result->restart_lsn = sle64_to_cpu(selected_area->current_lsn);
	result->latest_lsn = result->restart_lsn;
	clean = !*dirty_out;

close_volume:
	free(selected);
	selected = NULL;
	if (log_na) {
		ntfs_attr_close(log_na);
		log_na = NULL;
	}
	if (log_ni) {
		ntfs_inode_close(log_ni);
		log_ni = NULL;
	}
	if (ctx.vol) {
		if (ntfs_umount(ctx.vol, TRUE))
			clean = 0;
		ctx.vol = NULL;
	}
out:
	while (ctx.firstaction) {
		struct ACTION_RECORD *next = ctx.firstaction->next;

		free(ctx.firstaction);
		ctx.firstaction = next;
	}
	for (i = 0; i < BUFFERCNT + BASEBLKS; ++i) {
		free(buffer_table[i]);
		buffer_table[i] = NULL;
	}
	for (i = 0; i < attrcount; ++i)
		free(attrtable[i]);
	free(attrtable);
	attrtable = NULL;
	attrcount = 0;
	free(rh_examined_pages);
	rh_examined_pages = NULL;
	/* A failed probe is deliberately non-fatal; the full path diagnoses it. */
	if (!clean)
		memset(result, 0, sizeof(*result));
	errno = 0;
	return clean;
}

int roothealth_log_replay_plan_authorized(const char *device_name,
		struct rh_writer *writer,
		const struct rh_replay_slot_authority_provider *provider,
		struct rh_log_result *result)
{
	return roothealth_log_replay_plan_common(device_name, writer, provider,
		result, NULL, 0);
}

int roothealth_log_replay_plan_mounted(ntfs_volume *volume,
		struct rh_writer *writer, size_t checkpoint,
		struct rh_log_result *result)
{
	if (!volume) {
		errno = EINVAL;
		return -1;
	}
	return roothealth_log_replay_plan_common(writer ? writer->path : NULL,
		writer, NULL, result, volume, checkpoint);
}

int roothealth_log_replay_plan(const char *device_name,
		struct rh_writer *writer, struct rh_log_result *result)
{
	return roothealth_log_replay_plan_authorized(device_name, writer, NULL,
		result);
}
