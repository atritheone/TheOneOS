
#ifndef ROOTHEALTH_FORMAT3_H
#define ROOTHEALTH_FORMAT3_H

#include "roothealth_orchestrator.h"
#include "roothealth_report.h"

/*
 * Serialize the bounded public envelope.  This slice deliberately reports an
 * incomplete coverage ledger and an unresolved fail-closed issue, so it can
 * never manufacture exit 0 while the remaining repair families are absent.
 */
int rh_format3_publish(struct rh_report *report, const struct rh_cli *cli,
		const struct rh_device_evidence *device,
		const struct rh_scan_evidence *initial,
		const struct rh_scan_evidence *final,
		const struct rh_foundation_evidence *foundation,
		const struct rh_repair_evidence *repair, int result);

#endif
