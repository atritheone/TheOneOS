#!"/the one/software/python/bin/python" -B

"""
calculator.py

calculator is the standard calculator for The One OS.
"""



# imports
import atexit
import json
import os
import selectors
import shutil
import signal
import socket
import sys
from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext


DIAGNOSTICMODE = len(sys.argv) > 1 and sys.argv[1] == '--diagnostic'

if not DIAGNOSTICMODE:

    sys.path.insert(0, '/the one/build')

    from GODDESS.GODDESS import formatlog
    import graphics.graphics as gfx
    from graphics.graphics import drawline, drawrect, drawtextttf, fillrectfast
    from graphics.graphics import initbuffer, initttffont, measuretext, present as gfxpresent
    from graphics.graphics import managedclear, managedconfigure, manageddisable
    from graphics.graphics import managedmarkdamage, managedresponse, managedstate
    from graphics.graphics import managedsubmit, managedtick, uiscalefactor, displayuiscale

else:

    def formatlog(software, message):
        return f'[{software}] {message}'



# paths
APPPATH = '/the one/build/calculator/calculator.py'
LOGFILE = '/the one/logs/calculator.py.log'
WINDOWSOCK = '/.ephemeral/windowserver/accept.sock'
FONT = '/the one/resources/fonts/atkinsonhyperlegiblenext.ttf'

# application
APPNAME = 'calculator'
APPROLE = 'window'
VERSION = 1
RUNNING = True
FOCUSED = True

# calculator state
DISPLAY = '0'
EXPRESSION = ''
ACCUMULATOR = None
PENDING = None
LASTOPERATOR = None
LASTOPERAND = None
NEWINPUT = True
ERROR = ''
MAXINPUTDIGITS = 16
MAXDISPLAYCHARS = 18
OPERATORS = {
    '+': '+',
    '-': '−',
    '*': '×',
    '/': '÷',
}

# window
BASEWINW = 420
BASEWINH = 590
WINID = None
BUF = None
WINW = BASEWINW
WINH = BASEWINH
SCREENW = 0
SCREENH = 0
UISCALE = 1.0
NEEDWINDOW = True
WSOCK = None
INBUF = b''
OUTBUF = bytearray()
SEL = selectors.DefaultSelector()

# graphics
COLOURBG = 0x000000
COLOURTEXT = 0xEFEFEF
COLOURSTATUS = 0x242424
COLOURDIVIDER = 0x3A3A3A
COLOURMUTED = 0x6A6A6A
COLOURERROR = 0xFF0000
COLOURHILITETEXT = 0x000000
GRAPHICSCPUOVERRIDE = (
    str(os.environ.get('T1OS_CALCULATOR_GRAPHICS', '')).strip().lower()
    in ('cpu', 'off', '0', 'false')
)
GRAPHICSSTATE = None if DIAGNOSTICMODE else managedstate(cpu=GRAPHICSCPUOVERRIDE)
GRAPHICSSCENE = []
REDRAW = True
HOVERBUTTON = None

# base measurements
BASEPAD = 12
BASEGAP = 7
BASEDISPLAYH = 142
BASEFONTSIZE = 21
BASESMALLFONT = 14
BASEDISPLAYFONT = 50
PAD = BASEPAD
GAP = BASEGAP
DISPLAYH = BASEDISPLAYH
FONTSIZE = BASEFONTSIZE
SMALLFONT = BASESMALLFONT
DISPLAYFONT = BASEDISPLAYFONT



# general functions
def log(message):

    try:

        os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)

        with open(LOGFILE, 'a', encoding='utf-8') as stream:
            stream.write(formatlog('calculator', str(message)) + '\n')

    except Exception:
        pass


def scale(value):

    try:
        return max(1, int(round(float(value) * float(UISCALE))))
    except Exception:
        return max(1, int(value))


def applyscale():

    global UISCALE, PAD, GAP, DISPLAYH, FONTSIZE, SMALLFONT, DISPLAYFONT

    try:

        UISCALE = displayuiscale(SCREENW, SCREENH, uiscalefactor())

    except Exception:
        UISCALE = 1.0

    PAD = scale(BASEPAD)
    GAP = scale(BASEGAP)
    DISPLAYH = scale(BASEDISPLAYH)
    FONTSIZE = scale(BASEFONTSIZE)
    SMALLFONT = scale(BASESMALLFONT)
    DISPLAYFONT = scale(BASEDISPLAYFONT)


def pointin(x, y, rect):

    return (
        int(rect[0]) <= int(x) < int(rect[0]) + int(rect[2])
        and int(rect[1]) <= int(y) < int(rect[1]) + int(rect[3])
    )


def redraw():

    global REDRAW
    REDRAW = True



# calculation functions
def currentvalue():

    if ERROR or DISPLAY == 'Error':
        raise InvalidOperation

    return Decimal(str(DISPLAY))


def formatnumber(value):

    value = Decimal(value)

    if not value.is_finite():
        raise InvalidOperation

    if value == 0:
        return '0'

    normal = value.normalize()
    plain = format(normal, 'f')

    if '.' in plain:
        plain = plain.rstrip('0').rstrip('.')

    if plain in ('', '-0'):
        plain = '0'

    if len(plain) <= MAXDISPLAYCHARS:
        return plain

    for places in range(10, 0, -1):

        scientific = format(value, f'.{places}E')
        coefficient, exponent = scientific.split('E', 1)
        coefficient = coefficient.rstrip('0').rstrip('.')
        exponent = str(int(exponent))
        compact = f'{coefficient}e{exponent}'

        if len(compact) <= MAXDISPLAYCHARS:
            return compact

    raise InvalidOperation


def seterror(message):

    global DISPLAY, EXPRESSION, ACCUMULATOR, PENDING, LASTOPERATOR
    global LASTOPERAND, NEWINPUT, ERROR

    DISPLAY = 'Error'
    EXPRESSION = str(message)[:64]
    ACCUMULATOR = None
    PENDING = None
    LASTOPERATOR = None
    LASTOPERAND = None
    NEWINPUT = True
    ERROR = str(message)[:64]


def clearall():

    global DISPLAY, EXPRESSION, ACCUMULATOR, PENDING, LASTOPERATOR
    global LASTOPERAND, NEWINPUT, ERROR

    DISPLAY = '0'
    EXPRESSION = ''
    ACCUMULATOR = None
    PENDING = None
    LASTOPERATOR = None
    LASTOPERAND = None
    NEWINPUT = True
    ERROR = ''


def beginentry():

    global EXPRESSION, LASTOPERATOR, LASTOPERAND

    if PENDING is None and NEWINPUT:
        EXPRESSION = ''
        LASTOPERATOR = None
        LASTOPERAND = None


def inputdigit(digit):

    global DISPLAY, NEWINPUT

    digit = str(digit)

    if digit not in '0123456789':
        return

    if ERROR:
        clearall()

    beginentry()

    if NEWINPUT:
        DISPLAY = digit
        NEWINPUT = False
        return

    if sum(character.isdigit() for character in DISPLAY) >= MAXINPUTDIGITS:
        return

    if DISPLAY == '0':
        DISPLAY = digit

    elif DISPLAY == '-0':
        DISPLAY = f'-{digit}'

    else:
        DISPLAY += digit


def inputdecimal():

    global DISPLAY, NEWINPUT

    if ERROR:
        clearall()

    beginentry()

    if NEWINPUT:
        DISPLAY = '0.'
        NEWINPUT = False

    elif '.' not in DISPLAY and 'e' not in DISPLAY.lower():
        DISPLAY += '.'


def backspace():

    global DISPLAY

    if ERROR:
        clearall()
        return

    if NEWINPUT:
        return

    DISPLAY = DISPLAY[:-1]

    if DISPLAY in ('', '-', '-0'):
        DISPLAY = '0'


def togglesign():

    global DISPLAY, NEWINPUT

    if ERROR:
        clearall()
        return

    beginentry()

    if NEWINPUT and PENDING is not None:

        DISPLAY = '-0'
        NEWINPUT = False
        return

    if DISPLAY.startswith('-'):
        DISPLAY = DISPLAY[1:]

    else:
        DISPLAY = f'-{DISPLAY}'

    NEWINPUT = False


def applyoperation(left, operator, right):

    left = Decimal(left)
    right = Decimal(right)

    with localcontext() as context:

        context.prec = 40

        if operator == '+':
            result = left + right

        elif operator == '-':
            result = left - right

        elif operator == '*':
            result = left * right

        elif operator == '/':

            if right == 0:
                raise DivisionByZero

            result = left / right

        else:
            raise InvalidOperation

    if not result.is_finite():
        raise InvalidOperation

    return result


def chooseoperator(operator):

    global DISPLAY, EXPRESSION, ACCUMULATOR, PENDING, LASTOPERATOR
    global LASTOPERAND, NEWINPUT

    if operator not in OPERATORS:
        return

    if ERROR:
        return

    if PENDING is not None and NEWINPUT:

        PENDING = operator
        EXPRESSION = f'{formatnumber(ACCUMULATOR)} {OPERATORS[operator]}'
        return

    value = currentvalue()

    if PENDING is not None and ACCUMULATOR is not None:

        value = applyoperation(ACCUMULATOR, PENDING, value)
        DISPLAY = formatnumber(value)

    ACCUMULATOR = value
    PENDING = operator
    LASTOPERATOR = None
    LASTOPERAND = None
    NEWINPUT = True
    EXPRESSION = f'{formatnumber(ACCUMULATOR)} {OPERATORS[operator]}'


def percent():

    global DISPLAY, NEWINPUT

    if ERROR:
        return

    value = currentvalue()

    with localcontext() as context:

        context.prec = 40

        if PENDING in ('+', '-') and ACCUMULATOR is not None:
            value = (ACCUMULATOR * value) / Decimal(100)

        else:
            value = value / Decimal(100)

    DISPLAY = formatnumber(value)
    NEWINPUT = False


def equals():

    global DISPLAY, EXPRESSION, ACCUMULATOR, PENDING, LASTOPERATOR
    global LASTOPERAND, NEWINPUT

    if ERROR:
        return

    if PENDING is not None:

        left = ACCUMULATOR if ACCUMULATOR is not None else currentvalue()
        right = left if NEWINPUT else currentvalue()
        result = applyoperation(left, PENDING, right)
        EXPRESSION = (
            f'{formatnumber(left)} {OPERATORS[PENDING]} '
            f'{formatnumber(right)} ='
        )
        LASTOPERATOR = PENDING
        LASTOPERAND = right
        PENDING = None
        ACCUMULATOR = None
        DISPLAY = formatnumber(result)
        NEWINPUT = True
        return

    if LASTOPERATOR is not None and LASTOPERAND is not None:

        left = currentvalue()
        result = applyoperation(left, LASTOPERATOR, LASTOPERAND)
        EXPRESSION = (
            f'{formatnumber(left)} {OPERATORS[LASTOPERATOR]} '
            f'{formatnumber(LASTOPERAND)} ='
        )
        DISPLAY = formatnumber(result)
        NEWINPUT = True


def press(action):

    try:

        if str(action).startswith('digit:'):
            inputdigit(str(action).split(':', 1)[1])

        elif action == 'decimal':
            inputdecimal()

        elif action == 'clear':
            clearall()

        elif action == 'backspace':
            backspace()

        elif action == 'sign':
            togglesign()

        elif action == 'percent':
            percent()

        elif str(action).startswith('operator:'):
            chooseoperator(str(action).split(':', 1)[1])

        elif action == 'equals':
            equals()

    except DivisionByZero:
        seterror('cannot divide by zero')

    except (InvalidOperation, OverflowError, ValueError, ArithmeticError):
        seterror('calculation error')

    redraw()



# layout functions
def displayrect():

    height = min(max(1, int(DISPLAYH)), max(1, int(WINH) - (PAD * 2)))
    return [PAD, PAD, max(1, int(WINW) - (PAD * 2)), height]


def buttons():

    display = displayrect()
    top = display[1] + display[3] + GAP
    bottom = max(top + 5, int(WINH) - PAD)
    availableheight = max(5, bottom - top - (GAP * 4))
    rowheight = max(1, availableheight // 5)
    availablewidth = max(4, int(WINW) - (PAD * 2) - (GAP * 3))
    columnwidth = max(1, availablewidth // 4)
    columns = []
    x = PAD

    for column in range(4):

        if column == 3:
            width = max(1, int(WINW) - PAD - x)

        else:
            width = columnwidth

        columns.append((x, width))
        x += width + GAP

    rows = []
    y = top

    for row in range(5):

        if row == 4:
            height = max(1, bottom - y)

        else:
            height = rowheight

        rows.append((y, height))
        y += height + GAP

    definitions = (
        ('clear', 'AC', 0, 0, 1),
        ('sign', '±', 0, 1, 1),
        ('percent', '%', 0, 2, 1),
        ('operator:/', '÷', 0, 3, 1),
        ('digit:7', '7', 1, 0, 1),
        ('digit:8', '8', 1, 1, 1),
        ('digit:9', '9', 1, 2, 1),
        ('operator:*', '×', 1, 3, 1),
        ('digit:4', '4', 2, 0, 1),
        ('digit:5', '5', 2, 1, 1),
        ('digit:6', '6', 2, 2, 1),
        ('operator:-', '−', 2, 3, 1),
        ('digit:1', '1', 3, 0, 1),
        ('digit:2', '2', 3, 1, 1),
        ('digit:3', '3', 3, 2, 1),
        ('operator:+', '+', 3, 3, 1),
        ('digit:0', '0', 4, 0, 2),
        ('decimal', '.', 4, 2, 1),
        ('equals', '=', 4, 3, 1),
    )
    values = []

    for action, label, row, column, span in definitions:

        x, _ = columns[column]
        y, height = rows[row]
        lastcolumn = column + span - 1
        right = columns[lastcolumn][0] + columns[lastcolumn][1]
        values.append({
            'action': action,
            'label': label,
            'rect': [x, y, max(1, right - x), height],
        })

    return values


def buttonat(x, y):

    for button in buttons():

        if pointin(x, y, button['rect']):
            return button

    return None


def textwidth(text, size):

    try:
        return max(0, int(measuretext(str(text), int(size), FONT)))
    except Exception:
        return max(0, int(round(len(str(text)) * int(size) * 0.56)))


def fitfontsize(text, maximum, preferred, minimum):

    size = max(1, int(preferred))
    minimum = max(1, int(minimum))

    while size > minimum and textwidth(text, size) > max(1, int(maximum)):
        size -= 1

    return size


def baseline(y, size):

    try:

        face = gfx.getttfface(FONT)

        if face is None:
            return int(y)

        face.set_pixel_sizes(0, int(size))
        ascender = int(face.size.ascender >> 6)
        return int(y) + int(size) - ascender

    except Exception:
        return int(y)


def textnode(x, y, text, size, colour, clip):

    return {
        'kind': 'text',
        'x': max(0, int(x)),
        'y': max(0, int(baseline(y, size))),
        'text': str(text)[:128],
        'size': max(1, int(size)),
        'font': FONT,
        'color': int(colour),
        'clip': list(clip),
    }


def linenode(x0, y0, x1, y1, colour, clip):

    return {
        'kind': 'line',
        'points': [int(x0), int(y0), int(x1), int(y1)],
        'color': int(colour),
        'clip': list(clip),
    }


def buttonactive(button):

    action = str(button.get('action', ''))
    return (
        action.startswith('operator:')
        and PENDING == action.split(':', 1)[1]
        and NEWINPUT
    )


def buildscene():

    fullclip = [0, 0, int(WINW), int(WINH)]
    display = displayrect()
    commands = [{
        'kind': 'rectangle',
        'rect': list(fullclip),
        'color': COLOURBG,
        'clip': list(fullclip),
    }]
    title = 'calculator'
    commands.append(textnode(display[0], display[1], title, SMALLFONT, COLOURTEXT, display))
    expression = EXPRESSION or 'standard'
    expressionwidth = textwidth(expression, SMALLFONT)
    expressionx = max(display[0], display[0] + display[2] - expressionwidth)
    expressiony = display[1] + scale(30)
    commands.append(textnode(expressionx, expressiony, expression, SMALLFONT, COLOURMUTED if not ERROR else COLOURERROR, display))
    result = DISPLAY
    resultsize = fitfontsize(result, display[2], DISPLAYFONT, FONTSIZE)
    resultwidth = textwidth(result, resultsize)
    resultx = max(display[0], display[0] + display[2] - resultwidth)
    resulty = display[1] + display[3] - resultsize - scale(17)
    commands.append(textnode(resultx, resulty, result, resultsize, COLOURERROR if ERROR else COLOURTEXT, display))
    dividery = display[1] + display[3] - 1
    commands.append(linenode(display[0], dividery, display[0] + display[2], dividery, COLOURDIVIDER, fullclip))

    for button in buttons():

        x, y, width, height = button['rect']
        action = button['action']
        hover = action == HOVERBUTTON
        active = buttonactive(button)
        labelcolour = COLOURTEXT

        if action == 'equals':

            commands.append({
                'kind': 'rectangle',
                'rect': [x, y, width, height],
                'color': COLOURTEXT,
                'clip': list(fullclip),
            })
            labelcolour = COLOURHILITETEXT

        elif hover or active:

            commands.append({
                'kind': 'rectangle',
                'rect': [x, y, width, height],
                'color': COLOURSTATUS,
                'clip': list(fullclip),
            })

        commands.extend((
            linenode(x, y, x + width, y, COLOURDIVIDER, fullclip),
            linenode(x + width - 1, y, x + width - 1, y + height, COLOURDIVIDER, fullclip),
            linenode(x, y + height - 1, x + width, y + height - 1, COLOURDIVIDER, fullclip),
            linenode(x, y, x, y + height, COLOURDIVIDER, fullclip),
        ))

        if active:
            commands.append(linenode(x + 1, y + height - 2, x + width - 2, y + height - 2, COLOURTEXT, fullclip))

        label = button['label']
        usedsize = min(FONTSIZE, max(1, height - scale(12)))
        labelx = x + max(0, (width - textwidth(label, usedsize)) // 2)
        labely = y + max(0, (height - usedsize) // 2)
        commands.append(textnode(labelx, labely, label, usedsize, labelcolour, [x, y, width, height]))

    return commands



# managed graphics functions
def graphicssend(requestdata):

    try:
        sendws(requestdata)
        return True
    except Exception:
        return False


def graphicsconfigure(capabilities):

    return managedconfigure(
        GRAPHICSSTATE,
        capabilities,
        required=('rectangle', 'line', 'text'),
        cpu=GRAPHICSCPUOVERRIDE or not os.path.isfile(FONT),
    )


def submitscene():

    global GRAPHICSSCENE

    if not GRAPHICSSTATE.get('available') or not WINID:
        return False

    try:

        commands = buildscene()
        managedmarkdamage(
            GRAPHICSSTATE,
            [0, 0, int(WINW), int(WINH)],
            bounds=(int(WINW), int(WINH)),
        )
        managedsubmit(GRAPHICSSTATE, graphicssend, WINID, commands)

        if GRAPHICSSTATE.get('pending'):
            GRAPHICSSCENE = commands

        return bool(GRAPHICSSTATE.get('available'))

    except Exception as error:

        retained = manageddisable(GRAPHICSSTATE, f'calculator scene failed: {error}')
        log(f'managed graphics disabled {error}')
        return bool(retained)


def graphicsresponse(message):

    global GRAPHICSSCENE

    handled = managedresponse(GRAPHICSSTATE, message)

    if not GRAPHICSSTATE.get('available'):
        GRAPHICSSCENE = []
        redraw()

    return handled



# CPU graphics functions
def drawtextaligned(rect, text, size, colour, horizontal='center'):

    x, y, width, height = rect
    measured = textwidth(text, size)

    if horizontal == 'right':
        textx = max(x, x + width - measured)

    elif horizontal == 'left':
        textx = x

    else:
        textx = x + max(0, (width - measured) // 2)

    texty = y + max(0, (height - size) // 2)
    drawtextttf(textx, texty, str(text), colour, size, FONT)


def drawcpu():

    try:

        fillrectfast(0, 0, int(WINW), int(WINH), COLOURBG)
        display = displayrect()
        drawtextttf(display[0], display[1], 'calculator', COLOURTEXT, SMALLFONT, FONT)
        expression = EXPRESSION or 'standard'
        expressiony = display[1] + scale(30)
        expressionrect = [display[0], expressiony, display[2], SMALLFONT]
        drawtextaligned(expressionrect, expression, SMALLFONT, COLOURERROR if ERROR else COLOURMUTED, 'right')
        resultsize = fitfontsize(DISPLAY, display[2], DISPLAYFONT, FONTSIZE)
        resultrect = [
            display[0],
            display[1] + display[3] - resultsize - scale(17),
            display[2],
            resultsize,
        ]
        drawtextaligned(resultrect, DISPLAY, resultsize, COLOURERROR if ERROR else COLOURTEXT, 'right')
        dividery = display[1] + display[3] - 1
        drawline(display[0], dividery, display[0] + display[2], dividery, COLOURDIVIDER)

        for button in buttons():

            x, y, width, height = button['rect']
            action = button['action']
            hover = action == HOVERBUTTON
            active = buttonactive(button)
            labelcolour = COLOURTEXT

            if action == 'equals':

                fillrectfast(x, y, width, height, COLOURTEXT)
                labelcolour = COLOURHILITETEXT

            elif hover or active:
                fillrectfast(x, y, width, height, COLOURSTATUS)

            drawrect(x, y, width, height, COLOURDIVIDER)

            if active:
                drawline(x + 1, y + height - 2, x + width - 2, y + height - 2, COLOURTEXT)

            usedsize = min(FONTSIZE, max(1, height - scale(12)))
            drawtextaligned([x, y, width, height], button['label'], usedsize, labelcolour)

        gfxpresent()

        if WINID and not GRAPHICSSTATE.get('available'):
            sendws({
                'op': 'DAMAGE',
                'winid': WINID,
                'rect': [0, 0, int(WINW), int(WINH)],
            })

        return True

    except Exception as error:

        log(f'CPU draw error {error}')
        return False


def paint():

    global REDRAW

    if not REDRAW or not BUF or WINW < 1 or WINH < 1:
        return

    REDRAW = False

    if GRAPHICSSTATE.get('available'):
        submitscene()
    else:
        drawcpu()



# window server functions
def connectws():

    global WSOCK

    WSOCK = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    WSOCK.connect(WINDOWSOCK)
    WSOCK.setblocking(False)
    SEL.register(WSOCK, selectors.EVENT_READ | selectors.EVENT_WRITE)


def sendws(message):

    try:
        OUTBUF.extend(json.dumps(message, separators=(',', ':')).encode('utf-8') + b'\n')
    except Exception as error:
        log(f'windowserver send error {error}')


def flushws():

    if not OUTBUF or WSOCK is None:
        return

    try:

        sent = WSOCK.send(OUTBUF)
        del OUTBUF[:sent]

    except BlockingIOError:
        return

    except Exception as error:
        log(f'windowserver flush error {error}')


def recvws():

    global INBUF

    try:

        data = WSOCK.recv(65536)

        if not data:
            raise ConnectionError('windowserver disconnected')

        INBUF += data

    except BlockingIOError:
        return []

    messages = []

    while b'\n' in INBUF:

        line, INBUF = INBUF.split(b'\n', 1)

        if line.strip():
            messages.append(json.loads(line.decode('utf-8')))

    return messages


def createwindow():

    sendws({
        'op': 'CREATE_WINDOW',
        'role': APPROLE,
        'title': APPNAME,
        'current': APPNAME,
        'path': APPPATH,
        'w': scale(BASEWINW),
        'h': scale(BASEWINH),
        'x': 140,
        'y': 80,
        'pid': os.getpid(),
    })


def mapwindow():

    sendws({'op': 'MAP', 'winid': WINID})


def rebind():

    mapping = getattr(gfx, '_FILE_MAP', None)

    if mapping:

        try:
            mapping.close()
        except Exception:
            pass

        setattr(gfx, '_FILE_MAP', None)

    descriptor = getattr(gfx, '_FILE_FD', None)

    if descriptor:

        try:
            os.close(descriptor)
        except Exception:
            pass

        setattr(gfx, '_FILE_FD', None)

    setattr(gfx, '_IS_FILE_BUFFER', False)
    initbuffer(BUF, WINW, WINH)


def resized(message):

    global WINW, WINH, BUF

    if GRAPHICSSTATE.get('available') and WINID:
        managedclear(GRAPHICSSTATE, graphicssend, WINID)

    WINW = max(1, int(message.get('w', WINW)))
    WINH = max(1, int(message.get('h', WINH)))
    BUF = message.get('buffer', BUF)
    rebind()
    redraw()


def handlews(message):

    global WINID, BUF, WINW, WINH, SCREENW, SCREENH
    global NEEDWINDOW, RUNNING, FOCUSED, HOVERBUTTON

    operation = str(message.get('op', ''))

    if operation in ('GRAPHICS_COMMITTED', 'GRAPHICS_CLEARED'):

        graphicsresponse(message)
        return

    if operation in ('GRAPHICS_BEGUN', 'GRAPHICS_COMMAND_ADDED', 'GRAPHICS_INFO'):
        return

    if operation == 'WELCOME':

        framebuffer = message.get('fb', {})
        SCREENW = int(framebuffer.get('w', 0))
        SCREENH = int(framebuffer.get('h', 0))
        applyscale()
        graphicsconfigure(message.get('graphics', {}))

        if NEEDWINDOW:

            NEEDWINDOW = False
            createwindow()

        return

    if operation == 'FB_SIZE':

        SCREENW = int(message.get('w', SCREENW))
        SCREENH = int(message.get('h', SCREENH))
        applyscale()

        if NEEDWINDOW:

            NEEDWINDOW = False
            createwindow()

        redraw()
        return

    if operation == 'WINDOW_CREATED':

        WINID = int(message.get('winid'))
        BUF = message.get('buffer')
        WINW = max(1, int(message.get('w', WINW)))
        WINH = max(1, int(message.get('h', WINH)))
        initbuffer(BUF, WINW, WINH)
        initttffont(FONT, FONTSIZE)
        initttffont(FONT, SMALLFONT)
        initttffont(FONT, DISPLAYFONT)
        redraw()
        return

    if operation == 'WINDOW_MAPPED':

        redraw()
        return

    if operation == 'RESIZED':

        resized(message)
        return

    if operation == 'FOCUS':

        FOCUSED = bool(message.get('focused', message.get('value', True)))

        if not FOCUSED and HOVERBUTTON is not None:

            HOVERBUTTON = None
            redraw()

        return

    if operation == 'CLOSE':

        RUNNING = False
        sendws({'op': 'CLOSE_ACK', 'pid': os.getpid()})
        return

    if operation == 'ERROR':

        if str(message.get('code', '')).startswith('graphics_'):
            graphicsresponse(message)

        log(f'windowserver error code={message.get("code")} detail={message.get("detail")}')



# input functions
def keyinput(message):

    state = str(message.get('state', 'down')).lower()

    if state not in ('down', 'repeat'):
        return

    key = str(message.get('key', '')).upper()

    if key in ('ENTER', 'RETURN', 'KPENTER'):
        press('equals')

    elif key == 'BACKSPACE':
        press('backspace')

    elif key in ('DELETE', 'ESC', 'CLEAR'):
        press('clear')

    elif key in ('DECIMAL', 'KPDECIMAL'):
        press('decimal')

    elif key in ('ADD', 'KPADD'):
        press('operator:+')

    elif key in ('SUBTRACT', 'KPSUBTRACT'):
        press('operator:-')

    elif key in ('MULTIPLY', 'KPMULTIPLY'):
        press('operator:*')

    elif key in ('DIVIDE', 'KPDIVIDE'):
        press('operator:/')

    elif key.startswith('NUM') and key[3:].isdigit() and len(key[3:]) == 1:
        press(f'digit:{key[3:]}')


def textinput(message):

    text = str(message.get('text', ''))

    for character in text:

        if character in '0123456789':
            press(f'digit:{character}')

        elif character in '.,':
            press('decimal')

        elif character == '+':
            press('operator:+')

        elif character == '-':
            press('operator:-')

        elif character in ('*', 'x', 'X', '×'):
            press('operator:*')

        elif character in ('/', '÷'):
            press('operator:/')

        elif character in ('=', '\r', '\n'):
            press('equals')

        elif character == '%':
            press('percent')


def pointermotion(message):

    global HOVERBUTTON

    button = buttonat(message.get('x', 0), message.get('y', 0))
    action = button.get('action') if button else None

    if action != HOVERBUTTON:

        HOVERBUTTON = action
        redraw()


def pointerbutton(message):

    pressed = message.get('pressed')

    if pressed is None:
        pressed = str(message.get('state', 'down')).lower() == 'down'

    if not pressed or int(message.get('button', 1)) != 1:
        return

    button = buttonat(message.get('x', 0), message.get('y', 0))

    if button is not None:
        press(button['action'])



# diagnostic functions
def diagnostic():

    global WINW, WINH, HOVERBUTTON

    result = {
        'version': VERSION,
        'passed': False,
        'checks': {},
        'errors': [],
    }
    statenaming = (
        'DISPLAY', 'EXPRESSION', 'ACCUMULATOR', 'PENDING', 'LASTOPERATOR',
        'LASTOPERAND', 'NEWINPUT', 'ERROR', 'WINW', 'WINH', 'HOVERBUTTON',
    )
    previous = {name: globals().get(name) for name in statenaming}

    def sequence(*actions):

        clearall()

        for action in actions:
            press(action)

        return DISPLAY

    try:

        if sequence('digit:1', 'digit:2', 'operator:+', 'digit:3', 'equals') != '15':
            raise RuntimeError('addition returned the wrong result')

        press('equals')

        if DISPLAY != '18':
            raise RuntimeError('repeated equals did not reuse the last operation')

        result['checks']['addition_and_repeat'] = DISPLAY

        operationresults = {
            'subtract': sequence('digit:5', 'operator:-', 'digit:8', 'equals'),
            'multiply': sequence('digit:8', 'operator:*', 'digit:7', 'equals'),
            'divide': sequence('digit:9', 'operator:/', 'digit:4', 'equals'),
            'chain': sequence('digit:2', 'operator:+', 'digit:3', 'operator:*', 'digit:4', 'equals'),
            'implicit_operand': sequence('digit:5', 'operator:+', 'equals'),
        }

        if operationresults != {
            'subtract': '-3',
            'multiply': '56',
            'divide': '2.25',
            'chain': '20',
            'implicit_operand': '10',
        }:
            raise RuntimeError(f'standard operations returned the wrong results: {operationresults}')

        result['checks']['standard_operations'] = operationresults

        if sequence('digit:0', 'decimal', 'digit:1', 'operator:+', 'digit:0', 'decimal', 'digit:2', 'equals') != '0.3':
            raise RuntimeError('decimal addition was not exact')

        result['checks']['decimal'] = DISPLAY

        if sequence('digit:2', 'digit:0', 'digit:0', 'operator:+', 'digit:1', 'digit:0', 'percent', 'equals') != '220':
            raise RuntimeError('contextual percent returned the wrong result')

        result['checks']['percent'] = DISPLAY

        if sequence('digit:9', 'operator:/', 'digit:0', 'equals') != 'Error' or ERROR != 'cannot divide by zero':
            raise RuntimeError('division by zero did not enter the expected error state')

        press('digit:7')

        if DISPLAY != '7' or ERROR:
            raise RuntimeError('digit input did not recover from an error')

        result['checks']['error_recovery'] = True

        if sequence('digit:1', 'digit:2', 'digit:3', 'backspace') != '12':
            raise RuntimeError('backspace returned the wrong result')

        press('sign')

        if DISPLAY != '-12':
            raise RuntimeError('sign toggle returned the wrong result')

        if sequence('digit:5', 'operator:+', 'sign', 'digit:2', 'equals') != '3':
            raise RuntimeError('sign toggle did not begin a negative operand')

        result['checks']['entry_controls'] = True
        WINW = BASEWINW
        WINH = BASEWINH
        HOVERBUTTON = None
        controls = buttons()

        if len(controls) != 19:
            raise RuntimeError(f'calculator defines {len(controls)} controls instead of 19')

        zero = next(button for button in controls if button['action'] == 'digit:0')
        one = next(button for button in controls if button['action'] == 'digit:1')

        if zero['rect'][2] <= one['rect'][2]:
            raise RuntimeError('zero control does not span two columns')

        result['checks']['responsive_controls'] = len(controls)
        scene = buildscene()
        texts = [str(command.get('text', '')) for command in scene if command.get('kind') == 'text']

        if (
            not scene
            or scene[0].get('rect') != [0, 0, WINW, WINH]
            or scene[0].get('color') != COLOURBG
            or not all(label in texts for label in ('AC', '±', '%', '÷', '×', '−', '+', '='))
        ):
            raise RuntimeError('calculator scene is incomplete')

        if len(scene) >= 128:
            raise RuntimeError('calculator scene exceeded its command budget')

        result['checks']['managed_scene'] = len(scene)

        if (
            COLOURBG,
            COLOURTEXT,
            COLOURSTATUS,
            COLOURDIVIDER,
            COLOURMUTED,
            COLOURERROR,
        ) != (0x000000, 0xEFEFEF, 0x242424, 0x3A3A3A, 0x6A6A6A, 0xFF0000):
            raise RuntimeError('calculator palette does not match the t1os application palette')

        result['checks']['t1os_palette'] = True
        result['passed'] = True

    except Exception as error:
        result['errors'].append(str(error))

    finally:

        for name, value in previous.items():
            globals()[name] = value

    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['passed'] else 1


def graphicsdiagnostic():

    global WINW, WINH, BUF, HOVERBUTTON

    result = {
        'version': VERSION,
        'passed': False,
        'checks': {},
        'errors': [],
    }
    root = f'/.ephemeral/calculator-diagnostic-{os.getpid()}'
    bufferpath = os.path.join(root, 'window.bgra')
    statenaming = (
        'DISPLAY', 'EXPRESSION', 'ACCUMULATOR', 'PENDING', 'LASTOPERATOR',
        'LASTOPERAND', 'NEWINPUT', 'ERROR', 'WINW', 'WINH', 'BUF',
        'HOVERBUTTON',
    )
    previous = {name: globals().get(name) for name in statenaming}

    try:

        os.makedirs(root, mode=0o700, exist_ok=False)
        WINW = BASEWINW
        WINH = BASEWINH
        HOVERBUTTON = 'digit:7'

        with open(bufferpath, 'wb') as stream:
            stream.truncate(WINW * WINH * 4)

        BUF = bufferpath
        initbuffer(BUF, WINW, WINH)
        initttffont(FONT, FONTSIZE)
        initttffont(FONT, SMALLFONT)
        initttffont(FONT, DISPLAYFONT)
        clearall()
        press('digit:1')
        press('digit:2')
        press('operator:+')
        press('digit:3')
        press('equals')

        if DISPLAY != '15' or EXPRESSION != '12 + 3 =':
            raise RuntimeError('calculator diagnostic state is incorrect')

        result['checks']['calculation'] = DISPLAY
        scene = buildscene()
        texts = [str(command.get('text', '')) for command in scene if command.get('kind') == 'text']

        if not scene or scene[0].get('rect') != [0, 0, WINW, WINH] or scene[0].get('color') != COLOURBG:
            raise RuntimeError('calculator did not build a complete opaque scene')

        if not all(label in texts for label in ('calculator', '15', 'AC', '÷', '×', '−', '+', '=')):
            raise RuntimeError('calculator managed scene is missing visible controls')

        if len(scene) >= 128:
            raise RuntimeError('calculator scene exceeded its command budget')

        result['checks']['managed_scene'] = True
        result['checks']['command_budget'] = len(scene)

        if not drawcpu():
            raise RuntimeError('calculator CPU fallback did not render')

        if os.path.getsize(bufferpath) != WINW * WINH * 4:
            raise RuntimeError('calculator CPU surface has the wrong byte size')

        with open(bufferpath, 'rb') as stream:

            background = stream.read(4)
            stream.seek(((WINH // 2) * WINW + (WINW // 2)) * 4)
            content = stream.read(4)

        if len(background) != 4 or background[:3] != b'\x00\x00\x00':
            raise RuntimeError('calculator CPU fallback did not preserve its black background')

        if len(content) != 4:
            raise RuntimeError('calculator CPU fallback did not produce a complete surface')

        result['checks']['cpu_fallback'] = True
        result['checks']['responsive_controls'] = len(buttons()) == 19
        result['checks']['t1os_palette'] = (
            COLOURBG,
            COLOURTEXT,
            COLOURSTATUS,
            COLOURDIVIDER,
            COLOURMUTED,
            COLOURERROR,
        ) == (0x000000, 0xEFEFEF, 0x242424, 0x3A3A3A, 0x6A6A6A, 0xFF0000)

        if not result['checks']['responsive_controls'] or not result['checks']['t1os_palette']:
            raise RuntimeError('calculator UI contract is incomplete')

        result['passed'] = True

    except Exception as error:
        result['errors'].append(str(error))

    finally:

        for name, value in previous.items():
            globals()[name] = value

        shutil.rmtree(root, ignore_errors=True)

    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['passed'] else 1



# core functions
def cleanup():

    try:

        if WSOCK is not None:
            WSOCK.close()

    except Exception:
        pass


def terminate(signum, frame):

    global RUNNING
    RUNNING = False


def initapp():

    global NEEDWINDOW

    connectws()
    sendws({'op': 'HELLO'})
    sendws({'op': 'SUBSCRIBE', 'types': ['fbsize']})
    NEEDWINDOW = True

    while RUNNING and WINID is None:

        events = SEL.select(timeout=0.1)

        for key, mask in events:

            if key.fileobj is WSOCK and mask & selectors.EVENT_READ:

                for message in recvws():
                    handlews(message)

            if key.fileobj is WSOCK and mask & selectors.EVENT_WRITE:
                flushws()

        flushws()

    paint()
    flushws()
    mapwindow()
    sendws({'op': 'RAISE', 'winid': WINID})
    sendws({'op': 'FOCUS_SET', 'winid': WINID})
    flushws()


def pulse():

    global RUNNING

    events = SEL.select(timeout=0.04)

    for key, mask in events:

        if key.fileobj is not WSOCK:
            continue

        if mask & selectors.EVENT_READ:

            try:
                messages = recvws()

            except Exception as error:

                log(f'windowserver receive error {error}')
                RUNNING = False
                return

            for message in messages:

                handlews(message)
                operation = str(message.get('op', ''))

                if operation == 'KEY':
                    keyinput(message)

                elif operation == 'TEXT':
                    textinput(message)

                elif operation == 'POINTER_MOTION':
                    pointermotion(message)

                elif operation == 'POINTER_BUTTON':
                    pointerbutton(message)

        if mask & selectors.EVENT_WRITE:
            flushws()

    if GRAPHICSSTATE.get('available') and not managedtick(GRAPHICSSTATE):

        if WINID:
            sendws({'op': 'GRAPHICS_CLEAR', 'winid': WINID})

        redraw()

    paint()
    flushws()


def main():

    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    initapp()

    while RUNNING:
        pulse()

    flushws()
    return 0


if __name__ == '__main__':

    if DIAGNOSTICMODE:
        raise SystemExit(diagnostic())

    if len(sys.argv) > 1 and sys.argv[1] in ('graphics-diagnostic', '--graphics-diagnostic'):
        raise SystemExit(graphicsdiagnostic())

    raise SystemExit(main())
