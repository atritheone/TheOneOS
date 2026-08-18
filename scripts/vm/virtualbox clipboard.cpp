/**
 * T1OS VirtualBox Shared Clipboard bridge.
 *
 * This deliberately has no X11 or Wayland dependency.  It speaks Oracle's
 * Guest Additions HGCM protocol and exchanges UTF-8 text with the T1OS Python
 * supervisor over a private stdin/stdout protocol.  It supports text, HTML,
 * bitmap and URI-list clipboard formats without an X11 or Wayland dependency.
 */

#include <iprt/errcore.h>
#include <iprt/initterm.h>
#include <iprt/mem.h>
#include <iprt/string.h>
#include <iprt/thread.h>

#include <VBox/GuestHost/SharedClipboard.h>
#include <VBox/GuestHost/SharedClipboard-transfers.h>
#include <VBox/GuestHost/clipboard-helper.h>
#include <VBox/HostServices/VBoxClipboardSvc.h>
#include <VBox/VBoxGuestLib.h>

#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>


#define T1_CLIPBOARD_MAX_BYTES       UINT32_C(16777216)
#define T1_CLIPBOARD_LINE_BYTES      (T1_CLIPBOARD_MAX_BYTES * 2U + 64U)
#define T1_CLIPBOARD_POLL_MS         20


static volatile sig_atomic_t g_fRunning = 1;
static VBGLR3SHCLCMDCTX g_Ctx;
static char *g_pszText = NULL;
static uint32_t g_cbText = 0;
static void *g_pvHtml = NULL;
static uint32_t g_cbHtml = 0;
static void *g_pvBitmap = NULL;
static uint32_t g_cbBitmap = 0;
static void *g_pvFiles = NULL;
static uint32_t g_cbFiles = 0;
static bool g_fConnected = false;
static SHCLTRANSFERCTX g_TransferCtx;
static SHCLHTTPCONTEXT g_HttpCtx;
static bool g_fTransferCtx = false;
static bool g_fHttpCtx = false;
static volatile bool g_fHostFileRead = false;


static void t1Info(const char *pszOperation, uint64_t uValue1, uint64_t uValue2);


static SHCLFORMATS t1GuestFormats(void)
{
    SHCLFORMATS fFormats = VBOX_SHCL_FMT_NONE;
    if (g_pszText)
        fFormats |= VBOX_SHCL_FMT_UNICODETEXT;
    if (g_pvHtml)
        fFormats |= VBOX_SHCL_FMT_HTML;
    if (g_pvBitmap)
        fFormats |= VBOX_SHCL_FMT_BITMAP;
    if (g_pvFiles)
        fFormats |= VBOX_SHCL_FMT_URI_LIST;
    return fFormats;
}


static int t1ReportGuestFormats(void)
{
    SHCLFORMATS const fFormats = t1GuestFormats();
    int const rc = VbglR3ClipboardReportFormats(g_Ctx.idClient, fFormats);
    if (RT_SUCCESS(rc))
        t1Info("guest-formats", fFormats, 0);
    return rc;
}


static void t1Stop(int iSignal)
{
    RT_NOREF(iSignal);
    g_fRunning = 0;
}


static void t1Error(const char *pszOperation, int rc)
{
    fprintf(stdout, "ERROR %s %d\n", pszOperation, rc);
    fflush(stdout);
}


static void t1Info(const char *pszOperation, uint64_t uValue1, uint64_t uValue2)
{
    fprintf(stdout, "INFO %s %llu %llu\n", pszOperation,
            (unsigned long long)uValue1, (unsigned long long)uValue2);
    fflush(stdout);
}


static void t1TransferUnregister(PSHCLTRANSFER pTransfer)
{
    if (   pTransfer
        && ShClTransferGetDir(pTransfer) == SHCLTRANSFERDIR_FROM_REMOTE
        && ShClTransferHttpServerIsInitialized(&g_HttpCtx.HttpServer))
    {
        ShClTransferHttpServerUnregisterTransfer(&g_HttpCtx.HttpServer, pTransfer);
        ShClTransferHttpServerMaybeStop(&g_HttpCtx);
    }
}


static DECLCALLBACK(int) t1TransferInitialize(PSHCLTRANSFERCALLBACKCTX pCbCtx)
{
    PSHCLTRANSFER pTransfer = pCbCtx->pTransfer;
    if (ShClTransferGetDir(pTransfer) == SHCLTRANSFERDIR_TO_REMOTE)
    {
        if (!g_pvFiles || !g_cbFiles)
            return VERR_NO_DATA;
        return ShClTransferRootsSetFromStringListEx(pTransfer, (const char *)g_pvFiles,
                                                     g_cbFiles, "\r\n");
    }

    if (ShClTransferGetDir(pTransfer) == SHCLTRANSFERDIR_FROM_REMOTE)
    {
        int rc = ShClTransferRootListRead(pTransfer);
        if (RT_SUCCESS(rc) && ShClTransferRootsCount(pTransfer))
            rc = ShClTransferHttpServerRegisterTransfer(&g_HttpCtx.HttpServer, pTransfer);
        return rc;
    }
    return VINF_SUCCESS;
}


static DECLCALLBACK(void) t1TransferRegistered(PSHCLTRANSFERCALLBACKCTX pCbCtx,
                                               PSHCLTRANSFERCTX pTransferCtx)
{
    RT_NOREF(pTransferCtx);
    if (ShClTransferGetDir(pCbCtx->pTransfer) == SHCLTRANSFERDIR_FROM_REMOTE)
    {
        int const rc = ShClTransferHttpServerMaybeStart(&g_HttpCtx);
        if (RT_FAILURE(rc))
            t1Error("transfer-http-start", rc);
    }
}


static DECLCALLBACK(void) t1TransferUnregistered(PSHCLTRANSFERCALLBACKCTX pCbCtx,
                                                 PSHCLTRANSFERCTX pTransferCtx)
{
    RT_NOREF(pTransferCtx);
    t1TransferUnregister(pCbCtx->pTransfer);
}


static DECLCALLBACK(void) t1TransferCompleted(PSHCLTRANSFERCALLBACKCTX pCbCtx, int rc)
{
    RT_NOREF(rc);
    t1TransferUnregister(pCbCtx->pTransfer);
}


static DECLCALLBACK(void) t1TransferError(PSHCLTRANSFERCALLBACKCTX pCbCtx, int rc)
{
    t1TransferCompleted(pCbCtx, rc);
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


static int t1SetText(const char *pszHex, size_t cchHex)
{
    if (cchHex & 1U)
        return VERR_INVALID_PARAMETER;

    size_t const cbText = cchHex / 2U;
    if (cbText > T1_CLIPBOARD_MAX_BYTES)
        return VERR_TOO_MUCH_DATA;

    char *pszText = (char *)RTMemAlloc(cbText + 1U);
    if (!pszText)
        return VERR_NO_MEMORY;

    for (size_t i = 0; i < cbText; ++i)
    {
        int const iHigh = t1HexNibble(pszHex[i * 2U]);
        int const iLow  = t1HexNibble(pszHex[i * 2U + 1U]);
        if (iHigh < 0 || iLow < 0)
        {
            RTMemFree(pszText);
            return VERR_INVALID_PARAMETER;
        }
        pszText[i] = (char)((iHigh << 4) | iLow);
    }
    pszText[cbText] = '\0';

    if (cbText)
    {
        int const rc = RTStrValidateEncodingEx(pszText, cbText,
                                               RTSTR_VALIDATE_ENCODING_EXACT_LENGTH);
        if (RT_FAILURE(rc))
        {
            RTMemFree(pszText);
            return rc;
        }
    }

    RTMemFree(g_pszText);
    g_pszText = pszText;
    g_cbText = (uint32_t)cbText;
    return t1ReportGuestFormats();
}


static int t1SetRaw(const char *pszHex, size_t cchHex, void **ppvData, uint32_t *pcbData)
{
    if ((cchHex & 1U) || cchHex / 2U > T1_CLIPBOARD_MAX_BYTES)
        return VERR_TOO_MUCH_DATA;

    size_t const cbData = cchHex / 2U;
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
    RTMemFree(*ppvData);
    *ppvData = pbData;
    *pcbData = (uint32_t)cbData;
    return t1ReportGuestFormats();
}


static int t1Clear(void)
{
    RTMemFree(g_pszText); g_pszText = NULL; g_cbText = 0;
    RTMemFree(g_pvHtml); g_pvHtml = NULL; g_cbHtml = 0;
    RTMemFree(g_pvBitmap); g_pvBitmap = NULL; g_cbBitmap = 0;
    RTMemFree(g_pvFiles); g_pvFiles = NULL; g_cbFiles = 0;
    return t1ReportGuestFormats();
}


static void t1EmitHost(const char *pszKind, const void *pvData, size_t cbData)
{
    static char const s_szHex[] = "0123456789abcdef";

    fprintf(stdout, "HOST %s ", pszKind);
    const unsigned char *pbData = (const unsigned char *)pvData;
    for (size_t i = 0; i < cbData; ++i)
    {
        unsigned char const b = pbData[i];
        fputc(s_szHex[b >> 4], stdout);
        fputc(s_szHex[b & 0x0f], stdout);
    }
    fputc('\n', stdout);
    fflush(stdout);
}


static int t1ReadHost(SHCLFORMAT fFormat)
{
    void *pvData = NULL;
    uint32_t cbData = 0;
    int rc = VbglR3ClipboardReadDataEx(&g_Ctx, fFormat,
                                       &pvData, &cbData);
    if (RT_FAILURE(rc))
        return rc;

    if (fFormat == VBOX_SHCL_FMT_HTML || fFormat == VBOX_SHCL_FMT_URI_LIST)
    {
        t1EmitHost(fFormat == VBOX_SHCL_FMT_HTML ? "HTML" : "FILES",
                   pvData ? pvData : "", pvData ? cbData : 0);
        RTMemFree(pvData);
        return VINF_SUCCESS;
    }

    if (fFormat == VBOX_SHCL_FMT_BITMAP)
    {
        void *pvBitmap = NULL;
        size_t cbBitmap = 0;
        rc = pvData ? ShClDibToBmp(pvData, cbData, &pvBitmap, &cbBitmap) : VERR_INVALID_PARAMETER;
        if (RT_SUCCESS(rc))
            t1EmitHost("BITMAP", pvBitmap, cbBitmap);
        RTMemFree(pvBitmap);
        RTMemFree(pvData);
        return rc;
    }

    if (!pvData || cbData < sizeof(RTUTF16) || cbData % sizeof(RTUTF16))
    {
        RTMemFree(pvData);
        t1EmitHost("TEXT", "", 0);
        return VINF_SUCCESS;
    }

    size_t const cwcData = cbData / sizeof(RTUTF16);
    size_t cbUtf8 = 0;
    rc = ShClUtf16LenUtf8((PCRTUTF16)pvData, cwcData, &cbUtf8);
    if (RT_SUCCESS(rc) && cbUtf8 <= T1_CLIPBOARD_MAX_BYTES)
    {
        char *pszUtf8 = (char *)RTMemAlloc(cbUtf8 + 1U);
        if (pszUtf8)
        {
            size_t cbActual = 0;
            rc = ShClConvUtf16CRLFToUtf8LF((PCRTUTF16)pvData, cwcData,
                                           pszUtf8, cbUtf8 + 1U, &cbActual);
            if (RT_SUCCESS(rc))
                t1EmitHost("TEXT", pszUtf8, cbActual);
            RTMemFree(pszUtf8);
        }
        else
            rc = VERR_NO_MEMORY;
    }
    else if (RT_SUCCESS(rc))
        rc = VERR_TOO_MUCH_DATA;

    RTMemFree(pvData);
    return rc;
}


static DECLCALLBACK(int) t1ReadHostFiles(RTTHREAD hThreadSelf, void *pvUser)
{
    RT_NOREF(hThreadSelf, pvUser);

    void *pvIgnored = NULL;
    uint32_t cbIgnored = 0;
    int rc = VbglR3ClipboardReadDataEx(&g_Ctx, VBOX_SHCL_FMT_URI_LIST,
                                        &pvIgnored, &cbIgnored);
    RTMemFree(pvIgnored);
    if (RT_SUCCESS(rc))
        rc = VbglR3ClipboardTransferRequest(&g_Ctx);
    if (RT_SUCCESS(rc))
        rc = ShClTransferHttpServerWaitForStatusChange(&g_HttpCtx.HttpServer,
                 SHCLHTTPSERVERSTATUS_TRANSFER_REGISTERED, SHCL_TIMEOUT_DEFAULT_MS);
    if (RT_SUCCESS(rc))
    {
        PSHCLTRANSFER pTransfer = ShClTransferHttpServerGetTransferLast(&g_HttpCtx.HttpServer);
        rc = pTransfer ? ShClTransferWaitForStatus(pTransfer, SHCL_TIMEOUT_DEFAULT_MS,
                                                    SHCLTRANSFERSTATUS_INITIALIZED)
                       : VERR_NOT_FOUND;
        if (RT_SUCCESS(rc))
        {
            char *pszData = NULL;
            size_t cbData = 0;
            rc = ShClTransferHttpConvertToStringList(&g_HttpCtx.HttpServer, pTransfer,
                                                      &pszData, &cbData);
            if (RT_SUCCESS(rc))
                t1EmitHost("FILES", pszData, cbData);
            RTStrFree(pszData);
        }
    }
    if (RT_FAILURE(rc))
        t1Error("host-files", rc);
    g_fHostFileRead = false;
    return rc;
}


static int t1WriteGuest(SHCLFORMAT fFormat)
{
    if ((fFormat & VBOX_SHCL_FMT_HTML) && g_pvHtml)
        return VbglR3ClipboardWriteDataEx(&g_Ctx, VBOX_SHCL_FMT_HTML, g_pvHtml, g_cbHtml);

    if ((fFormat & VBOX_SHCL_FMT_URI_LIST) && g_pvFiles)
        return VbglR3ClipboardWriteDataEx(&g_Ctx, VBOX_SHCL_FMT_URI_LIST, g_pvFiles, g_cbFiles);

    if ((fFormat & VBOX_SHCL_FMT_BITMAP) && g_pvBitmap)
    {
        const void *pvDib = NULL;
        size_t cbDib = 0;
        int rc = ShClBmpGetDib(g_pvBitmap, g_cbBitmap, &pvDib, &cbDib);
        if (RT_SUCCESS(rc) && cbDib <= UINT32_MAX)
            return VbglR3ClipboardWriteDataEx(&g_Ctx, VBOX_SHCL_FMT_BITMAP, (void *)pvDib, (uint32_t)cbDib);
        return rc;
    }

    if (!(fFormat & VBOX_SHCL_FMT_UNICODETEXT) || !g_pszText)
        return VbglR3ClipboardWriteDataEx(&g_Ctx, fFormat, NULL, 0);

    if (!g_cbText)
    {
        RTUTF16 wcEmpty = 0;
        return VbglR3ClipboardWriteDataEx(&g_Ctx, VBOX_SHCL_FMT_UNICODETEXT,
                                          &wcEmpty, sizeof(wcEmpty));
    }

    PRTUTF16 pwszText = NULL;
    size_t cwcText = 0;
    int rc = ShClConvUtf8LFToUtf16CRLF(g_pszText, g_cbText, &pwszText, &cwcText);
    if (RT_SUCCESS(rc))
    {
        size_t const cbText = (cwcText + 1U) * sizeof(RTUTF16);
        if (cbText <= UINT32_MAX)
            rc = VbglR3ClipboardWriteDataEx(&g_Ctx, VBOX_SHCL_FMT_UNICODETEXT,
                                            pwszText, (uint32_t)cbText);
        else
            rc = VERR_TOO_MUCH_DATA;
    }

    RTMemFree(pwszText);
    if (RT_FAILURE(rc))
        VbglR3ClipboardWriteDataEx(&g_Ctx, VBOX_SHCL_FMT_UNICODETEXT, NULL, 0);
    return rc;
}


static int t1HandleEvent(PVBGLR3CLIPBOARDEVENT pEvent)
{
    switch (pEvent->enmType)
    {
        case VBGLR3CLIPBOARDEVENTTYPE_REPORT_FORMATS:
            t1Info("host-formats", pEvent->u.fReportedFormats, 0);
            if (pEvent->u.fReportedFormats & VBOX_SHCL_FMT_URI_LIST)
            {
                if (!g_fHostFileRead)
                {
                    g_fHostFileRead = true;
                    RTTHREAD hThread = NIL_RTTHREAD;
                    int const rc = RTThreadCreate(&hThread, t1ReadHostFiles, NULL, 0,
                                                   RTTHREADTYPE_IO, RTTHREADFLAGS_WAITABLE,
                                                   "t1-clip-files");
                    if (RT_FAILURE(rc))
                        g_fHostFileRead = false;
                    return rc;
                }
                return VINF_SUCCESS;
            }
            if (pEvent->u.fReportedFormats & VBOX_SHCL_FMT_BITMAP)
                return t1ReadHost(VBOX_SHCL_FMT_BITMAP);
            if (pEvent->u.fReportedFormats & VBOX_SHCL_FMT_HTML)
                return t1ReadHost(VBOX_SHCL_FMT_HTML);
            if (pEvent->u.fReportedFormats & VBOX_SHCL_FMT_UNICODETEXT)
                return t1ReadHost(VBOX_SHCL_FMT_UNICODETEXT);
            fputs("HOSTEMPTY\n", stdout);
            fflush(stdout);
            return VINF_SUCCESS;

        case VBGLR3CLIPBOARDEVENTTYPE_READ_DATA:
            t1Info("host-read", pEvent->u.fReadData, 0);
            return t1WriteGuest(pEvent->u.fReadData);

        case VBGLR3CLIPBOARDEVENTTYPE_QUIT:
            g_fRunning = 0;
            return VINF_SUCCESS;

        case VBGLR3CLIPBOARDEVENTTYPE_TRANSFER_STATUS:
            return VINF_SUCCESS;

        default:
            return VERR_NOT_SUPPORTED;
    }
}


static DECLCALLBACK(int) t1EventThread(RTTHREAD hThreadSelf, void *pvUser)
{
    RT_NOREF(hThreadSelf, pvUser);

    while (g_fRunning)
    {
        uint32_t idMessage = 0;
        uint32_t cParameters = 0;
        int rc = VbglR3ClipboardMsgPeekWait(&g_Ctx, &idMessage, &cParameters, NULL);
        if (rc == VERR_INTERRUPTED)
            continue;
        if (RT_FAILURE(rc))
        {
            if (g_fRunning)
            {
                t1Error("host-wait", rc);
                RTThreadSleep(RT_MS_1SEC);
            }
            continue;
        }

        PVBGLR3CLIPBOARDEVENT pEvent =
            (PVBGLR3CLIPBOARDEVENT)RTMemAllocZ(sizeof(VBGLR3CLIPBOARDEVENT));
        if (!pEvent)
        {
            t1Error("host-memory", VERR_NO_MEMORY);
            break;
        }

        rc = VbglR3ClipboardEventGetNextEx(idMessage, cParameters, &g_Ctx,
                                            &g_TransferCtx, pEvent);
        if (RT_SUCCESS(rc))
            rc = t1HandleEvent(pEvent);
        VbglR3ClipboardEventFree(pEvent);

        if (RT_FAILURE(rc) && rc != VERR_NOT_SUPPORTED)
        {
            t1Error("host-event", rc);
            /*
             * Host clipboard contents can disappear or change format while a
             * read is in flight.  This is recoverable and must not tear down
             * the HGCM client: Windows only permits one clipboard client and
             * reconnecting can leave guest-to-host copying unavailable while
             * the backend is still releasing the previous connection.
             */
            RTThreadSleep(10);
        }
    }

    g_fRunning = 0;
    return VINF_SUCCESS;
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
    if (!strcmp(pszLine, "CLEAR"))
        return t1Clear();
    if (cchLine >= 9U && !memcmp(pszLine, "SET TEXT ", 9U))
        return t1SetText(pszLine + 9U, cchLine - 9U);
    if (cchLine >= 9U && !memcmp(pszLine, "SET HTML ", 9U))
        return t1SetRaw(pszLine + 9U, cchLine - 9U, &g_pvHtml, &g_cbHtml);
    if (cchLine >= 11U && !memcmp(pszLine, "SET BITMAP ", 11U))
        return t1SetRaw(pszLine + 11U, cchLine - 11U, &g_pvBitmap, &g_cbBitmap);
    if (cchLine >= 10U && !memcmp(pszLine, "SET FILES ", 10U))
        return t1SetRaw(pszLine + 10U, cchLine - 10U, &g_pvFiles, &g_cbFiles);
    if (cchLine >= 4U && !memcmp(pszLine, "SET ", 4U))
        return t1SetText(pszLine + 4U, cchLine - 4U);
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
    {
        t1Error("init-user", rc);
        return 11;
    }

    rc = ShClTransferCtxInit(&g_TransferCtx);
    if (RT_FAILURE(rc))
    {
        VbglR3Term();
        return 12;
    }
    g_fTransferCtx = true;
    rc = ShClTransferHttpServerInit(&g_HttpCtx.HttpServer);
    if (RT_FAILURE(rc))
    {
        ShClTransferCtxDestroy(&g_TransferCtx);
        VbglR3Term();
        return 13;
    }
    g_fHttpCtx = true;

    RT_ZERO(g_Ctx);
    rc = VbglR3ClipboardConnectEx(&g_Ctx, VBOX_SHCL_GF_0_CONTEXT_ID);
    if (RT_FAILURE(rc))
    {
        t1Error("connect", rc);
        VbglR3Term();
        return 12;
    }
    g_fConnected = true;

    RT_ZERO(g_Ctx.Transfers.Callbacks);
    g_Ctx.Transfers.Callbacks.pfnOnInitialize = t1TransferInitialize;
    g_Ctx.Transfers.Callbacks.pfnOnRegistered = t1TransferRegistered;
    g_Ctx.Transfers.Callbacks.pfnOnUnregistered = t1TransferUnregistered;
    g_Ctx.Transfers.Callbacks.pfnOnCompleted = t1TransferCompleted;
    g_Ctx.Transfers.Callbacks.pfnOnError = t1TransferError;

    char *pszLine = (char *)RTMemAlloc(T1_CLIPBOARD_LINE_BYTES);
    if (!pszLine)
    {
        VbglR3ClipboardDisconnectEx(&g_Ctx);
        VbglR3Term();
        return 13;
    }

    RTTHREAD hEventThread = NIL_RTTHREAD;
    rc = RTThreadCreate(&hEventThread, t1EventThread, NULL, 0,
                        RTTHREADTYPE_IO, RTTHREADFLAGS_WAITABLE, "t1-clipboard");
    if (RT_FAILURE(rc))
    {
        t1Error("event-thread", rc);
        RTMemFree(pszLine);
        VbglR3ClipboardDisconnectEx(&g_Ctx);
        VbglR3Term();
        return 14;
    }

    fputs("READY\n", stdout);
    fflush(stdout);
    t1Info("protocol", g_Ctx.fUseLegacyProtocol ? 1U : 0U, g_Ctx.fHostFeatures);

    while (g_fRunning)
    {
        struct pollfd PollFd;
        PollFd.fd = STDIN_FILENO;
        PollFd.events = POLLIN | POLLHUP | POLLERR;
        PollFd.revents = 0;

        int const rcPoll = poll(&PollFd, 1, T1_CLIPBOARD_POLL_MS);
        if (rcPoll > 0 && (PollFd.revents & POLLIN))
        {
            if (!fgets(pszLine, T1_CLIPBOARD_LINE_BYTES, stdin))
                g_fRunning = 0;
            else
            {
                int const rcCommand = t1ProcessCommand(pszLine);
                if (RT_FAILURE(rcCommand))
                    t1Error("command", rcCommand);
            }
        }
        else if (rcPoll > 0 && (PollFd.revents & (POLLHUP | POLLERR)))
            g_fRunning = 0;
        else if (rcPoll < 0 && errno != EINTR)
            g_fRunning = 0;

    }

    g_fRunning = 0;
    if (g_fConnected)
    {
        VbglR3ClipboardDisconnectEx(&g_Ctx);
        g_fConnected = false;
    }

    int rcThread = VINF_SUCCESS;
    rc = RTThreadWait(hEventThread, RT_MS_5SEC, &rcThread);
    if (RT_FAILURE(rc))
        t1Error("event-thread-wait", rc);

    RTMemFree(pszLine);
    RTMemFree(g_pszText);
    RTMemFree(g_pvHtml);
    RTMemFree(g_pvBitmap);
    RTMemFree(g_pvFiles);
    if (g_fHttpCtx)
        ShClTransferHttpServerDestroy(&g_HttpCtx.HttpServer);
    if (g_fTransferCtx)
        ShClTransferCtxDestroy(&g_TransferCtx);
    VbglR3Term();
    return 0;
}
