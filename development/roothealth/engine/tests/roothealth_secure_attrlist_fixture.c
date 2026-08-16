#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "attrib.h"
#include "device.h"
#include "dir.h"
#include "inode.h"
#include "lcnalloc.h"
#include "logging.h"
#include "runlist.h"
#include "volume.h"

static int64_t fixture_write(struct ntfs_device *device, const void *buffer,
		int64_t count, int64_t offset, void *opaque)
{
	(void)opaque;
	return device && device->d_ops && device->d_ops->pwrite ?
		device->d_ops->pwrite(device, buffer, count, offset) : -1;
}

static int move_attribute(ntfs_inode *inode, ATTR_TYPES type,
		const ntfschar *name, uint32_t name_length, VCN lowest_vcn)
{
	ntfs_attr_search_ctx *context;
	int result = -1;

	context = ntfs_attr_get_search_ctx(inode, NULL);
	if (!context)
		return -1;
	if (ntfs_attr_lookup(type, name, name_length, CASE_SENSITIVE, lowest_vcn,
			NULL, 0, context) ||
			ntfs_attr_record_move_away(context, 0))
		goto out;
	result = 0;
out:
	ntfs_attr_put_search_ctx(context);
	return result;
}

static int fragment_sds(ntfs_volume *volume, ntfs_attr *sds,
		size_t *run_count_out)
{
	unsigned char *bytes = NULL;
	runlist *old_runs, *new_runs = NULL;
	LCN *spacers = NULL;
	uint64_t cluster_count, i;
	int result = -1;

	if (!volume || !sds || !NAttrNonResident(sds) ||
			ntfs_attr_map_whole_runlist(sds) || sds->data_size <= 0 ||
			(uint64_t)sds->data_size > SIZE_MAX)
		return -1;
	cluster_count = ((uint64_t)sds->allocated_size +
		volume->cluster_size - 1U) >> volume->cluster_size_bits;
	if (cluster_count < 300U || cluster_count > SIZE_MAX / sizeof(*new_runs) -
			1U || cluster_count - 1U > SIZE_MAX / sizeof(*spacers)) {
		errno = ERANGE;
		return -1;
	}
	bytes = malloc((size_t)sds->data_size);
	new_runs = calloc((size_t)cluster_count + 1U, sizeof(*new_runs));
	spacers = calloc((size_t)cluster_count - 1U, sizeof(*spacers));
	if (!bytes || !new_runs || !spacers ||
			ntfs_attr_pread(sds, 0, sds->data_size, bytes) != sds->data_size)
		goto out;
	for (i = 0; i < cluster_count; i++) {
		runlist *allocated = ntfs_cluster_alloc(volume, (VCN)i, 1, -1,
			DATA_ZONE);

		if (!allocated || allocated[0].length != 1 || allocated[0].lcn < 0) {
			free(allocated);
			goto out;
		}
		new_runs[i] = allocated[0];
		free(allocated);
		if (i + 1U < cluster_count) {
			allocated = ntfs_cluster_alloc(volume, 0, 1, -1, DATA_ZONE);
			if (!allocated || allocated[0].length != 1 ||
					allocated[0].lcn < 0) {
				free(allocated);
				goto out;
			}
			spacers[i] = allocated[0].lcn;
			free(allocated);
		}
	}
	new_runs[cluster_count].vcn = (VCN)cluster_count;
	new_runs[cluster_count].lcn = LCN_ENOENT;
	if (ntfs_rl_pwrite(volume, new_runs, 0, 0, sds->data_size, bytes) !=
			sds->data_size)
		goto out;
	old_runs = sds->rl;
	sds->rl = new_runs;
	new_runs = NULL;
	NAttrSetFullyMapped(sds);
	NAttrSetRunlistDirty(sds);
	if (ntfs_attr_update_mapping_pairs(sds, 0)) {
		sds->rl = old_runs;
		goto out;
	}
	{
		unsigned char *verify = malloc((size_t)sds->data_size);

		if (!verify || ntfs_attr_pread(sds, 0, sds->data_size, verify) !=
				sds->data_size || memcmp(verify, bytes, (size_t)sds->data_size)) {
			free(verify);
			errno = EUCLEAN;
			goto out;
		}
		free(verify);
	}
	if (ntfs_cluster_free_from_rl(volume, old_runs))
		goto out;
	free(old_runs);
	for (i = 0; i + 1U < cluster_count; i++)
		if (ntfs_cluster_free_basic(volume, spacers[i], 1))
			goto out;
	*run_count_out = (size_t)cluster_count;
	result = 0;
out:
	free(spacers);
	free(new_runs);
	free(bytes);
	return result;
}

int main(int argc, char **argv)
{
	ntfs_volume *volume = NULL;
	ntfs_inode *inode = NULL;
	ntfs_attr *sds = NULL;
	size_t run_count = 0;
	unsigned long move_count = 7U;
	int skip_fragment = getenv("RH_SECURE_ATTRLIST_SKIP_FRAGMENT") != NULL;
	int result = 1;
	const char *phase = "arguments";

	if (argc != 2 && argc != 3)
		return 64;
	if (argc == 3) {
		char *end = NULL;

		errno = 0;
		move_count = strtoul(argv[2], &end, 10);
		if (errno || !end || *end || move_count > 7U)
			return 64;
	}
	ntfs_log_set_handler(ntfs_log_handler_stderr);
	ntfs_log_set_levels(NTFS_LOG_LEVEL_ERROR | NTFS_LOG_LEVEL_PERROR |
		NTFS_LOG_LEVEL_WARNING);
	phase = "mount";
	volume = ntfs_mount(argv[1], 0);
	if (!volume || ntfs_device_roothealth_install_plan_write(volume->dev,
			fixture_write, NULL))
		goto out;
	phase = "open-record9";
	inode = ntfs_inode_open(volume, FILE_Secure);
	if (!inode)
		goto out;
	if (!skip_fragment) {
		phase = "open-sds";
		sds = ntfs_attr_open(inode, AT_DATA, STREAM_SDS, 4);
		if (!sds)
			goto out;
		phase = "fragment-sds";
		if (fragment_sds(volume, sds, &run_count))
			goto out;
		ntfs_attr_close(sds);
		sds = NULL;
	} else if (!NInoAttrList(inode)) {
		errno = ENOENT;
		goto out;
	}
	phase = "move-sds";
	if (move_count >= 1U &&
			move_attribute(inode, AT_DATA, STREAM_SDS, 4, 0))
		goto out;
	phase = "move-sdh-root";
	if (move_count >= 2U &&
			move_attribute(inode, AT_INDEX_ROOT, NTFS_INDEX_SDH, 4, 0))
		goto out;
	phase = "move-sii-root";
	if (move_count >= 3U &&
			move_attribute(inode, AT_INDEX_ROOT, NTFS_INDEX_SII, 4, 0))
		goto out;
	phase = "move-sdh-allocation";
	if (move_count >= 4U && move_attribute(inode, AT_INDEX_ALLOCATION,
			NTFS_INDEX_SDH, 4, 0))
		goto out;
	phase = "move-sii-allocation";
	if (move_count >= 5U && move_attribute(inode, AT_INDEX_ALLOCATION,
			NTFS_INDEX_SII, 4, 0))
		goto out;
	phase = "move-sdh-bitmap";
	if (move_count >= 6U &&
			move_attribute(inode, AT_BITMAP, NTFS_INDEX_SDH, 4, 0))
		goto out;
	phase = "move-sii-bitmap";
	if (move_count >= 7U &&
			move_attribute(inode, AT_BITMAP, NTFS_INDEX_SII, 4, 0))
		goto out;
	phase = "sync";
	if (ntfs_inode_sync(inode))
		goto out;
	fprintf(stderr, "secure attrlist fixture fragmented_sds_runs=%zu "
		"moved=%lu skip_fragment=%d\n", run_count, move_count,
		skip_fragment);
	result = 0;
out:
	if (sds)
		ntfs_attr_close(sds);
	if (inode)
		ntfs_inode_close(inode);
	if (volume && ntfs_umount(volume, 0) && !result)
		result = 1;
	if (result)
		fprintf(stderr, "secure attrlist fixture phase=%s errno=%d (%s)\n",
			phase, errno, strerror(errno));
	return result;
}
