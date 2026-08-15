

"""
write in.py

A single command text writer for brick.
"""



# imports
import sys

sys.path.insert(0, '/the one/build')

from architect.architect import check



# core function
def writetextin():

    # define arguments
    args = sys.argv[1:]

    # interactive literal mode whenever a message argument exists
    if len(args) >= 2:

        # require at least a message and a file argument
        if len(args) < 2:

            sys.stderr.write("missing message andor file\n")
            sys.exit(1)

        # define text to write in
        literal = args[0]

        # strip input
        if len(literal) >= 2 and literal[0] in ('|', '"', "'") and literal[-1] == literal[0]:

            literal = literal[1:-1]

        # define target file paths
        files = args[1:]

    # if running non-interactively
    else:

        # all arguments are files
        literal = None
        files = args

    # if no file given
    if not files:

        sys.stderr.write("missing file\n")
        sys.exit(1)

    # define file objects
    outs = []

    for path in files:

        try:

            try:

                allowed = check(path)

            except Exception as e:

                # architect check error
                sys.stderr.write(f"error checking architect for {path} {e}\n")
                sys.exit(1)

            if not allowed:

                # architect denied write
                sys.stderr.write(f"permission denied")
                sys.exit(1)

            # open files to append
            outs.append(open(path, "a"))

        except OSError as e:

            # write in error opening path
            sys.stderr.write(f"error writing text in {path} {e.strerror}\n")
            sys.exit(1)

        except Exception as e:

            # other error opening path
            sys.stderr.write(f"error opening {path} {e}\n")
            sys.exit(1)

    # if a message is given
    if literal is not None:

        for f in outs:

            try:

                # write message to file
                f.write(literal + "\n")

            except OSError as e:

                # error writing to file
                sys.stderr.write(f"error writing text in {f.name} {e.strerror}\n")
                sys.exit(1)

            except Exception as e:

                # other error writing to file
                sys.stderr.write(f"error writing text in {f.name} {e}\n")
                sys.exit(1)

        # written in message
        for path in files:

            print(f"{path} written in")

    # otherwise
    else:

        # read the binary
        try:

            while True:

                # up to 4kb chunks
                chunk = sys.stdin.buffer.read(4096)

                if not chunk:

                    break

                # write into buffer
                sys.stdout.buffer.write(chunk)

                for f in outs:

                    try:

                        # write decoded chunks
                        f.write(chunk.decode("utf-8", errors="replace"))

                    except OSError as e:

                        # error writing chunk to file
                        sys.stderr.write(f"error writing text in {f.name} {e.strerror}\n")
                        sys.exit(1)

                    except Exception as e:

                        # other error writing chunk
                        sys.stderr.write(f"error writing text in {f.name} {e}\n")
                        sys.exit(1)

        # user exit without saving
        except KeyboardInterrupt:

            pass

        except Exception as e:

            # other stdin read error
            sys.stderr.write(f"error reading stdin {e}\n")
            sys.exit(1)

    # close opened files
    for f in outs:


        f.close()

if __name__ == "__main__":

    writetextin()
