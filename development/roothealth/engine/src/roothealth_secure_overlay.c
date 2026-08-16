/* ROOTHEALTH_REPAIR_ROLE(TYPED_WAL_ADAPTER) ROOTHEALTH_IO_ROLE(PLANNER) */
#include "config.h"

#include <limits.h>
#include <stdint.h>

#include "device.h"
#include "mst.h"
#include "roothealth_secure_overlay.h"

int rh_secure_overlay_apply_data(ntfs_volume *volume, void *opaque)
{
	const struct rh_secure_overlay_data_context *context = opaque;
	size_t i;

	if (!volume || !volume->dev || !context || !context->writes ||
			!context->bytes || !context->count)
		return RH_OVERLAY_ACTION_ERROR;
	for (i = 0; i < context->count; i++)
		if (context->writes[i].offset > INT64_MAX ||
				context->writes[i].length > INT64_MAX ||
				ntfs_pwrite(volume->dev,
					(int64_t)context->writes[i].offset,
					(int64_t)context->writes[i].length,
					context->bytes[i]) !=
					(int64_t)context->writes[i].length)
			return RH_OVERLAY_ACTION_ERROR;
	return RH_OVERLAY_ACTION_OK;
}

int rh_secure_overlay_apply_mft(ntfs_volume *volume, void *opaque)
{
	struct rh_secure_overlay_mft_context *context = opaque;

	if (!volume || !volume->dev || !context || context->physical > INT64_MAX ||
			ntfs_mst_pwrite(volume->dev, (int64_t)context->physical, 1, 1024U,
				context->record) != 1)
		return RH_OVERLAY_ACTION_ERROR;
	return RH_OVERLAY_ACTION_OK;
}

int rh_secure_overlay_apply_operations(ntfs_volume *volume, void *opaque)
{
	struct rh_secure_overlay_operations_context *context = opaque;
	size_t i;

	if (!volume || !volume->dev || !context || !context->operations ||
			!context->count)
		return RH_OVERLAY_ACTION_ERROR;
	for (i = 0; i < context->count; i++) {
		struct rh_secure_overlay_operation *operation =
			&context->operations[i];

		if (!operation->bytes || !operation->length ||
				operation->physical > INT64_MAX ||
				operation->length > INT64_MAX)
			return RH_OVERLAY_ACTION_ERROR;
		if (operation->mst_block_size) {
			if (operation->length % operation->mst_block_size ||
					ntfs_mst_pwrite(volume->dev,
						(int64_t)operation->physical,
						operation->length / operation->mst_block_size,
						operation->mst_block_size, operation->bytes) !=
					(int64_t)(operation->length /
						operation->mst_block_size))
				return RH_OVERLAY_ACTION_ERROR;
		} else if (ntfs_pwrite(volume->dev,
				(int64_t)operation->physical, (int64_t)operation->length,
				operation->bytes) != (int64_t)operation->length)
			return RH_OVERLAY_ACTION_ERROR;
	}
	return RH_OVERLAY_ACTION_OK;
}
