import signal, sys
if hasattr(signal, "SIGPIPE"):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)          # paras --help | head ends quietly, as Unix tools do
from .cli import main
sys.exit(main())
