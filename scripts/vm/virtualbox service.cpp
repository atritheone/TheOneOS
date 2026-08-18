/**
 * T1OS VirtualBox integration service.
 *
 * This is deliberately smaller than the distribution-oriented VBoxService.
 * It exposes only the host facilities T1OS consumes and uses a private,
 * line-oriented stdin/stdout protocol with guestadditions.py.
 */

#include <iprt/critsect.h>
#include <iprt/errcore.h>
#include <iprt/initterm.h>
#include <iprt/mem.h>
#include <iprt/path.h>
#include <iprt/string.h>
#include <iprt/thread.h>
#include <iprt/time.h>

#include <VBox/GuestHost/DragAndDrop.h>
#include <VBox/GuestHost/DragAndDropDefs.h>
#include <VBox/VBoxGuestLib.h>
#include <VBox/VBoxGuestLibGuestProp.h>
#include <VBox/shflsvc.h>

#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <sys/time.h>
#include <unistd.h>


#define T1_LINE_MAX                 (2U * 1024U * 1024U + 4096U)
#define T1_DATA_MAX                 (1024U * 1024U)
#define T1_SHARE_POLL_MS            2000U
#define T1_TIME_POLL_MS             10000U


static volatile sig_atomic_t g_fRunning = 1;
static RTCRITSECT g_OutputLock;
static RTCRITSECT g_DragLock;
static bool g_fOutputLock = false;
static bool g_fDragLock = false;
static VBGLGSTPROPCLIENT g_PropertyClient;
static bool g_fPropertyConnected = false;
static char *g_pszGuestDragFormat = NULL;
static void *g_pvGuestDragData = NULL;
static uint32_t g_cbGuestDragData = 0;
static char *g_pszHostDropFormat = NULL;


static void t1Stop(int iSignal)
{
    RT_NOREF(iSignal);
    g_fRunning = 0;
}


static void t1OutputBegin(void)
{
    if (g_fOutputLock)
        RTCritSectEnter(&g_OutputLock);
}


static void t1OutputEnd(void)
{
    fflush(stdout);
    if (g_fOutputLock)
        RTCritSectLeave(&g_OutputLock);
}


static void t1Error(const char *pszOperation, int rc)
{
    t1OutputBegin();
    fprintf(stdout, "ERROR %s %d\n", pszOperation, rc);
    t1OutputEnd();
}


static void t1Info(const char *pszOperation, int64_t iValue1, int64_t iValue2)
{
    t1OutputBegin();
    fprintf(stdout, "INFO %s %lld %lld\n", pszOperation,
            (long long)iValue1, (long long)iValue2);
    t1OutputEnd();
}


static void t1WriteHex(const void *pvData, size_t cbData)
{
    static const char s_szHex[] = "0123456789abcdef";
    const unsigned char *pb = (const unsigned char *)pvData;
    for (size_t i = 0; i < cbData; ++i)
    {
        fputc(s_szHex[pb[i] >> 4], stdout);
        fputc(s_szHex[pb[i] & 0x0f], stdout);
    }
}


static int t1HexNibble(char ch)
{
    if (ch >= '0' && ch <= '9')
        return ch - '0';
    if (ch >= 'a' && ch <= 'f')
        return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'F')
        return ch - 'A' + 10;
    return -1;
}


static int t1DecodeHex(const char *pszHex, size_t cchHex, void **ppvData, uint32_t *pcbData)
{
    if (!pszHex || !ppvData || !pcbData || (cchHex & 1U))
        return VERR_INVALID_PARAMETER;

    size_t const cbData = cchHex / 2U;
    if (cbData > T1_DATA_MAX || cbData > UINT32_MAX)
        return VERR_TOO_MUCH_DATA;

    unsigned char *pbData = (unsigned char *)RTMemAlloc(cbData + 1U);
    if (!pbData)
        return VERR_NO_MEMORY;

    for (size_t i = 0; i < cbData; ++i)
    {
        int const iHigh = t1HexNibble(pszHex[i * 2U]);
        int const iLow = t1HexNibble(pszHex[i * 2U + 1U]);
        if (iHigh < 0 || iLow < 0)
        {
            RTMemFree(pbData);
            return VERR_INVALID_PARAMETER;
        }
        pbData[i] = (unsigned char)((iHigh << 4) | iLow);
    }
    pbData[cbData] = 0;

    *ppvData = pbData;
    *pcbData = (uint32_t)cbData;
    return VINF_SUCCESS;
}


static char *t1DecodeHexString(const char *pszHex)
{
    void *pvData = NULL;
    uint32_t cbData = 0;
    int rc = t1DecodeHex(pszHex, strlen(pszHex), &pvData, &cbData);
    if (RT_FAILURE(rc))
        return NULL;

    char *pszValue = (char *)pvData;
    if (memchr(pszValue, '\0', cbData))
    {
        RTMemFree(pszValue);
        return NULL;
    }
    pszValue[cbData] = '\0';
    return pszValue;
}


static void t1EmitPair(const char *pszKind, const char *pszName, const char *pszValue)
{
    if (!pszName)
        pszName = "";
    if (!pszValue)
        pszValue = "";

    t1OutputBegin();
    fprintf(stdout, "%s ", pszKind);
    t1WriteHex(pszName, strlen(pszName));
    fputc(' ', stdout);
    t1WriteHex(pszValue, strlen(pszValue));
    fputc('\n', stdout);
    t1OutputEnd();
}


static void t1EmitData(const char *pszKind, const char *pszFormat, const void *pvData, size_t cbData)
{
    if (!pszFormat)
        pszFormat = "";

    t1OutputBegin();
    fprintf(stdout, "%s ", pszKind);
    t1WriteHex(pszFormat, strlen(pszFormat));
    fputc(' ', stdout);
    if (pvData && cbData)
        t1WriteHex(pvData, cbData);
    fputc('\n', stdout);
    t1OutputEnd();
}


static void t1Sleep(unsigned cMillies)
{
    unsigned cLeft = cMillies;
    while (g_fRunning && cLeft)
    {
        unsigned const cSlice = cLeft > 100U ? 100U : cLeft;
        RTThreadSleep(cSlice);
        cLeft -= cSlice;
    }
}


/* Shared folders. */
static DECLCALLBACK(int) t1ShareThread(RTTHREAD hThreadSelf, void *pvUser)
{
    RT_NOREF(hThreadSelf, pvUser);
    uint32_t uGeneration = 0;

    while (g_fRunning)
    {
        HGCMCLIENTID idClient = 0;
        int rc = VbglR3SharedFolderConnect(&idClient);
        if (RT_FAILURE(rc))
        {
            t1Error("shares-connect", rc);
            t1Sleep(T1_SHARE_POLL_MS);
            continue;
        }

        while (g_fRunning)
        {
            PVBGLR3SHAREDFOLDERMAPPING paMappings = NULL;
            uint32_t cMappings = 0;
            rc = VbglR3SharedFolderGetMappings(idClient, true /* automount only */,
                                               &paMappings, &cMappings);
            if (RT_FAILURE(rc))
            {
                t1Error("shares-query", rc);
                break;
            }

            ++uGeneration;
            t1OutputBegin();
            fprintf(stdout, "SHARES %u %u\n", uGeneration, cMappings);
            t1OutputEnd();

            for (uint32_t i = 0; i < cMappings; ++i)
            {
                char *pszName = NULL;
                char *pszMountPoint = NULL;
                uint64_t fFlags = SHFL_MIF_AUTO_MOUNT;
                uint32_t uRootVersion = 0;
                rc = VbglR3SharedFolderQueryFolderInfo(idClient, paMappings[i].u32Root,
                                                       SHFL_MIQF_PATH,
                                                       &pszName, &pszMountPoint,
                                                       &fFlags, &uRootVersion);
                if (RT_FAILURE(rc))
                {
                    rc = VbglR3SharedFolderGetName(idClient, paMappings[i].u32Root, &pszName);
                    if (RT_FAILURE(rc))
                    {
                        t1Error("share-name", rc);
                        continue;
                    }
                }

                if (!pszMountPoint)
                    pszMountPoint = RTStrDup("");

                t1OutputBegin();
                fprintf(stdout, "SHARE %u %u %llu %u ", uGeneration,
                        paMappings[i].u32Root, (unsigned long long)fFlags, uRootVersion);
                t1WriteHex(pszName, strlen(pszName));
                fputc(' ', stdout);
                t1WriteHex(pszMountPoint, strlen(pszMountPoint));
                fputc('\n', stdout);
                t1OutputEnd();

                RTStrFree(pszName);
                RTStrFree(pszMountPoint);
            }

            VbglR3SharedFolderFreeMappings(paMappings);
            t1OutputBegin();
            fprintf(stdout, "SHARES_END %u\n", uGeneration);
            t1OutputEnd();
            t1Sleep(T1_SHARE_POLL_MS);
        }

        VbglR3SharedFolderDisconnect(idClient);
        t1Sleep(T1_SHARE_POLL_MS);
    }

    return VINF_SUCCESS;
}


/* Time synchronization. */
static bool t1TimeSyncEnabled(void)
{
    /* Clock mutation belongs exclusively to Operations.  Until a typed,
     * peer-validated broker exists, report this integration as unavailable
     * even when an older settings file says it is enabled. */
    return false;
}


static int t1AdjustTime(int64_t iDriftNs, bool fForce)
{
    RT_NOREF(iDriftNs, fForce);
    return VERR_NOT_SUPPORTED;
}


static DECLCALLBACK(int) t1TimeThread(RTTHREAD hThreadSelf, void *pvUser)
{
    RT_NOREF(hThreadSelf, pvUser);
    uint64_t uLastSession = 0;
    bool fFirst = true;
    bool fWasEnabled = true;

    while (g_fRunning)
    {
        bool const fEnabled = t1TimeSyncEnabled();
        if (!fEnabled)
        {
            if (fWasEnabled)
                t1Info("timesync-disabled", 0, 0);
            fWasEnabled = false;
            t1Sleep(T1_TIME_POLL_MS);
            continue;
        }
        if (!fWasEnabled)
            fFirst = true;
        fWasEnabled = true;

        RTTIMESPEC HostTime;
        RTTIMESPEC GuestTime;
        uint64_t uSession = 0;
        int rcHost = VbglR3GetHostTime(&HostTime);
        int rcSession = VbglR3QuerySessionId(&uSession);

        if (RT_SUCCESS(rcHost))
        {
            RTTimeNow(&GuestTime);
            int64_t const iDriftNs = RTTimeSpecGetNano(&HostTime) - RTTimeSpecGetNano(&GuestTime);
            bool const fSessionChanged = RT_SUCCESS(rcSession) && uLastSession && uSession != uLastSession;
            int rc = t1AdjustTime(iDriftNs, fFirst || fSessionChanged);
            if (RT_SUCCESS(rc))
                t1Info("timesync", iDriftNs / INT64_C(1000000), fSessionChanged ? 1 : 0);
            else
                t1Error("timesync-set", rc);
        }
        else
            t1Error("timesync-host", rcHost);

        if (RT_SUCCESS(rcSession))
            uLastSession = uSession;
        fFirst = false;
        t1Sleep(T1_TIME_POLL_MS);
    }

    return VINF_SUCCESS;
}


/* Guest properties. */
static int t1PropertyWrite(const char *pszName, const char *pszValue)
{
    if (!g_fPropertyConnected)
        return VERR_INVALID_STATE;
    return VbglGuestPropWrite(&g_PropertyClient, pszName, pszValue,
                              "TRANSIENT,TRANSRESET");
}


static DECLCALLBACK(int) t1PropertyThread(RTTHREAD hThreadSelf, void *pvUser)
{
    RT_NOREF(hThreadSelf, pvUser);
    VBGLGSTPROPCLIENT Client;
    RT_ZERO(Client);
    int rc = VbglGuestPropConnect(&Client);
    if (RT_FAILURE(rc))
    {
        t1Error("property-monitor-connect", rc);
        return rc;
    }

    char szPreviousVersion[128] = "";
    char szPreviousResume[128] = "";

    while (g_fRunning)
    {
        char szValue[128] = "";
        uint32_t cchActual = 0;
        rc = VbglGuestPropReadValue(&Client, "/VirtualBox/HostInfo/VBoxVer",
                                    szValue, sizeof(szValue), &cchActual);
        if (RT_SUCCESS(rc) && strcmp(szValue, szPreviousVersion))
        {
            RTStrCopy(szPreviousVersion, sizeof(szPreviousVersion), szValue);
            t1EmitPair("HOSTPROP", "/VirtualBox/HostInfo/VBoxVer", szValue);
        }

        szValue[0] = '\0';
        cchActual = 0;
        rc = VbglGuestPropReadValue(&Client, "/VirtualBox/HostInfo/ResumeCounter",
                                    szValue, sizeof(szValue), &cchActual);
        if (RT_SUCCESS(rc) && strcmp(szValue, szPreviousResume))
        {
            RTStrCopy(szPreviousResume, sizeof(szPreviousResume), szValue);
            t1EmitPair("HOSTPROP", "/VirtualBox/HostInfo/ResumeCounter", szValue);
        }

        t1Sleep(2000U);
    }

    VbglGuestPropDisconnect(&Client);
    return VINF_SUCCESS;
}


/* Drag and drop. */
static bool t1FormatInList(const char *pszList, const char *pszFormat)
{
    if (!pszList || !pszFormat)
        return false;
    size_t const cchFormat = strlen(pszFormat);
    const char *psz = pszList;
    while (*psz)
    {
        const char *pszEnd = strstr(psz, DND_PATH_SEPARATOR_STR);
        size_t const cch = pszEnd ? (size_t)(pszEnd - psz) : strlen(psz);
        if (cch == cchFormat && !memcmp(psz, pszFormat, cch))
            return true;
        if (!pszEnd)
            break;
        psz = pszEnd + strlen(DND_PATH_SEPARATOR_STR);
    }
    return false;
}


static char *t1ChooseHostFormat(const char *pszFormats)
{
    static const char *s_apszPreferred[] = {
        "text/uri-list",
        "text/html",
        "text/plain;charset=utf-8",
        "UTF8_STRING",
        "text/plain"
    };
    for (size_t i = 0; i < RT_ELEMENTS(s_apszPreferred); ++i)
        if (t1FormatInList(pszFormats, s_apszPreferred[i]))
            return RTStrDup(s_apszPreferred[i]);
    return NULL;
}


static void t1SetHostDropFormat(const char *pszFormat)
{
    RTCritSectEnter(&g_DragLock);
    RTStrFree(g_pszHostDropFormat);
    g_pszHostDropFormat = pszFormat ? RTStrDup(pszFormat) : NULL;
    RTCritSectLeave(&g_DragLock);
}


static char *t1GetHostDropFormat(void)
{
    RTCritSectEnter(&g_DragLock);
    char *pszFormat = g_pszHostDropFormat ? RTStrDup(g_pszHostDropFormat) : NULL;
    RTCritSectLeave(&g_DragLock);
    return pszFormat;
}


static void t1SetGuestDrag(const char *pszFormat, void *pvData, uint32_t cbData)
{
    RTCritSectEnter(&g_DragLock);
    RTStrFree(g_pszGuestDragFormat);
    RTMemFree(g_pvGuestDragData);
    g_pszGuestDragFormat = pszFormat ? RTStrDup(pszFormat) : NULL;
    g_pvGuestDragData = pvData;
    g_cbGuestDragData = cbData;
    RTCritSectLeave(&g_DragLock);
}


static void t1ClearGuestDrag(void)
{
    t1SetGuestDrag(NULL, NULL, 0);
}


static int t1DnDHandle(PVBGLR3GUESTDNDCMDCTX pCtx, PVBGLR3DNDEVENT pEvent)
{
    switch (pEvent->enmType)
    {
        case VBGLR3DNDEVENTTYPE_HG_ENTER:
        {
            char *pszFormat = t1ChooseHostFormat(pEvent->u.HG_Enter.pszFormats);
            t1SetHostDropFormat(pszFormat);
            t1EmitData("DND_ENTER", pszFormat ? pszFormat : "",
                       pEvent->u.HG_Enter.pszFormats,
                       pEvent->u.HG_Enter.pszFormats ? strlen(pEvent->u.HG_Enter.pszFormats) : 0);
            RTStrFree(pszFormat);
            return VINF_SUCCESS;
        }

        case VBGLR3DNDEVENTTYPE_HG_MOVE:
        {
            char *pszFormat = t1GetHostDropFormat();
            VBOXDNDACTION const enmAction = pszFormat ? VBOX_DND_ACTION_COPY : VBOX_DND_ACTION_IGNORE;
            int rc = VbglR3DnDHGSendAckOp(pCtx, enmAction);
            t1OutputBegin();
            fprintf(stdout, "DND_MOVE %u %u %u\n", pEvent->u.HG_Move.uXpos,
                    pEvent->u.HG_Move.uYpos, enmAction);
            t1OutputEnd();
            RTStrFree(pszFormat);
            return rc;
        }

        case VBGLR3DNDEVENTTYPE_HG_LEAVE:
            t1SetHostDropFormat(NULL);
            t1OutputBegin();
            fputs("DND_LEAVE\n", stdout);
            t1OutputEnd();
            return VINF_SUCCESS;

        case VBGLR3DNDEVENTTYPE_HG_DROP:
        {
            char *pszFormat = t1GetHostDropFormat();
            t1OutputBegin();
            fprintf(stdout, "DND_DROP %u %u %u\n", pEvent->u.HG_Drop.uXpos,
                    pEvent->u.HG_Drop.uYpos, pEvent->u.HG_Drop.dndActionDefault);
            t1OutputEnd();
            if (!pszFormat)
                return VbglR3DnDHGSendAckOp(pCtx, VBOX_DND_ACTION_IGNORE);
            int rc = VbglR3DnDHGSendReqData(pCtx, pszFormat);
            RTStrFree(pszFormat);
            return rc;
        }

        case VBGLR3DNDEVENTTYPE_HG_RECEIVE:
        {
            char *pszFormat = t1GetHostDropFormat();
            PVBGLR3GUESTDNDMETADATA pMeta = &pEvent->u.HG_Received.Meta;
            if (pMeta->enmType == VBGLR3GUESTDNDMETADATATYPE_URI_LIST)
            {
                char *pszRoots = NULL;
                size_t cbRoots = 0;
                int rc = DnDTransferListGetRootsEx(&pMeta->u.URI.Transfer,
                                                   DNDTRANSFERLISTFMT_NATIVE,
                                                   "", "\n", &pszRoots, &cbRoots);
                if (RT_SUCCESS(rc))
                {
                    t1EmitData("DND_FILES", "text/uri-list", pszRoots,
                               cbRoots ? cbRoots - 1U : 0U);
                    RTStrFree(pszRoots);
                }
                RTStrFree(pszFormat);
                t1SetHostDropFormat(NULL);
                return rc;
            }
            if (pMeta->enmType == VBGLR3GUESTDNDMETADATATYPE_RAW)
                t1EmitData("DND_DATA", pszFormat ? pszFormat : "application/octet-stream",
                           pMeta->u.Raw.pvMeta, pMeta->u.Raw.cbMeta);
            RTStrFree(pszFormat);
            t1SetHostDropFormat(NULL);
            return VINF_SUCCESS;
        }

        case VBGLR3DNDEVENTTYPE_CANCEL:
            t1SetHostDropFormat(NULL);
            t1OutputBegin();
            fputs("DND_CANCEL\n", stdout);
            t1OutputEnd();
            return VINF_SUCCESS;

#ifdef VBOX_WITH_DRAG_AND_DROP_GH
        case VBGLR3DNDEVENTTYPE_GH_REQ_PENDING:
        {
            RTCritSectEnter(&g_DragLock);
            int rc;
            if (g_pszGuestDragFormat && g_pvGuestDragData && g_cbGuestDragData)
                rc = VbglR3DnDGHSendAckPending(pCtx, VBOX_DND_ACTION_COPY,
                                               VBOX_DND_ACTION_COPY,
                                               g_pszGuestDragFormat,
                                               (uint32_t)strlen(g_pszGuestDragFormat) + 1U);
            else
                rc = VbglR3DnDGHSendAckPending(pCtx, VBOX_DND_ACTION_IGNORE,
                                               VBOX_DND_ACTION_IGNORE, "", 1U);
            RTCritSectLeave(&g_DragLock);
            return rc;
        }

        case VBGLR3DNDEVENTTYPE_GH_DROP:
        {
            RTCritSectEnter(&g_DragLock);
            int rc = VERR_NOT_FOUND;
            if (g_pszGuestDragFormat && g_pvGuestDragData && g_cbGuestDragData
                && t1FormatInList(g_pszGuestDragFormat, pEvent->u.GH_Drop.pszFormat))
                rc = VbglR3DnDGHSendData(pCtx, pEvent->u.GH_Drop.pszFormat,
                                         g_pvGuestDragData, g_cbGuestDragData);
            RTCritSectLeave(&g_DragLock);
            if (RT_FAILURE(rc))
                VbglR3DnDSendError(pCtx, rc);
            t1OutputBegin();
            fprintf(stdout, "DND_GUEST_SENT %d\n", rc);
            t1OutputEnd();
            return rc;
        }
#endif

        case VBGLR3DNDEVENTTYPE_QUIT:
            g_fRunning = 0;
            return VINF_SUCCESS;

        default:
            return VINF_SUCCESS;
    }
}


static DECLCALLBACK(int) t1DnDThread(RTTHREAD hThreadSelf, void *pvUser)
{
    RT_NOREF(hThreadSelf, pvUser);

    while (g_fRunning)
    {
        VBGLR3GUESTDNDCMDCTX Ctx;
        RT_ZERO(Ctx);
        int rc = VbglR3DnDConnect(&Ctx);
        if (RT_FAILURE(rc))
        {
            t1Error("dnd-connect", rc);
            t1Sleep(2000U);
            continue;
        }

        t1Info("dnd-connected", (int64_t)Ctx.fHostFeatures, (int64_t)Ctx.cbMaxChunkSize);
        while (g_fRunning)
        {
            PVBGLR3DNDEVENT pEvent = NULL;
            rc = VbglR3DnDEventGetNext(&Ctx, &pEvent);
            if (RT_FAILURE(rc))
            {
                if (g_fRunning)
                    t1Error("dnd-event", rc);
                break;
            }
            rc = t1DnDHandle(&Ctx, pEvent);
            VbglR3DnDEventFree(pEvent);
            if (RT_FAILURE(rc) && rc != VERR_NOT_FOUND && g_fRunning)
                t1Error("dnd-handle", rc);
        }

        VbglR3DnDDisconnect(&Ctx);
        t1Sleep(1000U);
    }
    return VINF_SUCCESS;
}


/* Command protocol. */
static int t1CommandProperty(char *pszArguments)
{
    char *pszSpace = strchr(pszArguments, ' ');
    if (!pszSpace)
        return VERR_INVALID_PARAMETER;
    *pszSpace++ = '\0';
    char *pszName = t1DecodeHexString(pszArguments);
    char *pszValue = t1DecodeHexString(pszSpace);
    if (!pszName || !pszValue)
    {
        RTMemFree(pszName);
        RTMemFree(pszValue);
        return VERR_INVALID_PARAMETER;
    }
    int rc = t1PropertyWrite(pszName, pszValue);
    RTMemFree(pszName);
    RTMemFree(pszValue);
    return rc;
}


static int t1CommandGuestDrag(char *pszArguments)
{
    char *pszSpace = strchr(pszArguments, ' ');
    if (!pszSpace)
        return VERR_INVALID_PARAMETER;
    *pszSpace++ = '\0';
    char *pszFormat = t1DecodeHexString(pszArguments);
    void *pvData = NULL;
    uint32_t cbData = 0;
    int rc = pszFormat ? t1DecodeHex(pszSpace, strlen(pszSpace), &pvData, &cbData)
                       : VERR_INVALID_PARAMETER;
    if (RT_SUCCESS(rc))
    {
        t1SetGuestDrag(pszFormat, pvData, cbData);
        pvData = NULL;
    }
    RTStrFree(pszFormat);
    RTMemFree(pvData);
    return rc;
}


static int t1ProcessCommand(char *pszLine)
{
    size_t cchLine = strlen(pszLine);
    while (cchLine && (pszLine[cchLine - 1U] == '\n' || pszLine[cchLine - 1U] == '\r'))
        pszLine[--cchLine] = '\0';

    if (!strcmp(pszLine, "QUIT"))
    {
        g_fRunning = 0;
        return VINF_SUCCESS;
    }
    if (!strcmp(pszLine, "GUESTDRAGCLEAR"))
    {
        t1ClearGuestDrag();
        return VINF_SUCCESS;
    }
    if (!strncmp(pszLine, "PROP ", 5U))
        return t1CommandProperty(pszLine + 5U);
    if (!strncmp(pszLine, "GUESTDRAG ", 10U))
        return t1CommandGuestDrag(pszLine + 10U);
    return VERR_INVALID_PARAMETER;
}


int main(void)
{
    setvbuf(stdout, NULL, _IOLBF, 0);
    signal(SIGINT, t1Stop);
    signal(SIGTERM, t1Stop);

    int rc = RTR3InitExeNoArguments(0);
    if (RT_FAILURE(rc))
        return 10;
    rc = VbglR3InitUser();
    if (RT_FAILURE(rc))
        return 11;

    rc = RTCritSectInit(&g_OutputLock);
    if (RT_FAILURE(rc))
        return 12;
    g_fOutputLock = true;
    rc = RTCritSectInit(&g_DragLock);
    if (RT_FAILURE(rc))
        return 13;
    g_fDragLock = true;

    RT_ZERO(g_PropertyClient);
    rc = VbglGuestPropConnect(&g_PropertyClient);
    if (RT_SUCCESS(rc))
        g_fPropertyConnected = true;
    else
        t1Error("property-connect", rc);

    RTTHREAD hShares = NIL_RTTHREAD;
    RTTHREAD hTime = NIL_RTTHREAD;
    RTTHREAD hProperties = NIL_RTTHREAD;
    RTTHREAD hDnD = NIL_RTTHREAD;
    int rcShares = RTThreadCreate(&hShares, t1ShareThread, NULL, 0, RTTHREADTYPE_IO,
                                  RTTHREADFLAGS_WAITABLE, "t1-shares");
    int rcTime = RTThreadCreate(&hTime, t1TimeThread, NULL, 0, RTTHREADTYPE_TIMER,
                                RTTHREADFLAGS_WAITABLE, "t1-timesync");
    int rcProperties = RTThreadCreate(&hProperties, t1PropertyThread, NULL, 0,
                                      RTTHREADTYPE_IO, RTTHREADFLAGS_WAITABLE, "t1-properties");
    int rcDnD = RTThreadCreate(&hDnD, t1DnDThread, NULL, 0, RTTHREADTYPE_IO,
                               RTTHREADFLAGS_WAITABLE, "t1-dnd");
    if (RT_FAILURE(rcShares) || RT_FAILURE(rcTime) || RT_FAILURE(rcProperties) || RT_FAILURE(rcDnD))
    {
        t1Error("thread-create", RT_FAILURE(rcShares) ? rcShares
                                  : RT_FAILURE(rcTime) ? rcTime
                                  : RT_FAILURE(rcProperties) ? rcProperties : rcDnD);
        g_fRunning = 0;
    }

    t1OutputBegin();
    fputs("READY\n", stdout);
    t1OutputEnd();

    char *pszLine = (char *)RTMemAlloc(T1_LINE_MAX);
    if (!pszLine)
        g_fRunning = 0;

    while (g_fRunning && pszLine)
    {
        struct pollfd PollFd;
        PollFd.fd = STDIN_FILENO;
        PollFd.events = POLLIN | POLLHUP | POLLERR;
        PollFd.revents = 0;
        int const rcPoll = poll(&PollFd, 1, 100);
        if (rcPoll > 0 && (PollFd.revents & POLLIN))
        {
            if (!fgets(pszLine, T1_LINE_MAX, stdin))
                g_fRunning = 0;
            else
            {
                rc = t1ProcessCommand(pszLine);
                if (RT_FAILURE(rc))
                    t1Error("command", rc);
            }
        }
        else if (rcPoll > 0 && (PollFd.revents & (POLLHUP | POLLERR)))
            g_fRunning = 0;
        else if (rcPoll < 0 && errno != EINTR)
            g_fRunning = 0;
    }

    g_fRunning = 0;
    RTMemFree(pszLine);
    if (g_fPropertyConnected)
        VbglGuestPropDisconnect(&g_PropertyClient);

    int rcThread = VINF_SUCCESS;
    if (hShares != NIL_RTTHREAD)
        RTThreadWait(hShares, RT_MS_5SEC, &rcThread);
    if (hTime != NIL_RTTHREAD)
        RTThreadWait(hTime, RT_MS_5SEC, &rcThread);
    if (hProperties != NIL_RTTHREAD)
        RTThreadWait(hProperties, RT_MS_5SEC, &rcThread);
    if (hDnD != NIL_RTTHREAD)
        RTThreadWait(hDnD, RT_MS_5SEC, &rcThread);

    t1ClearGuestDrag();
    t1SetHostDropFormat(NULL);
    if (g_fDragLock)
        RTCritSectDelete(&g_DragLock);
    if (g_fOutputLock)
        RTCritSectDelete(&g_OutputLock);
    VbglR3Term();
    return 0;
}
