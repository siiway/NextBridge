from contextlib import contextmanager
import sys
import traceback
import services.logger as log

# Initialize logger
l = log.get_logger()

def _handle_uncaught_exceptions(exc_type, exc_value, exc_traceback):
    """Global exception handler for uncaught exceptions."""
    if issubclass(exc_type, KeyboardInterrupt):
        # Call default handler for keyboard interrupt (e.g. Ctrl+C)
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Log the full traceback for debugging
    l.critical(
        "Unhandled exception caught:\n"
        + ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    )

# Install global exception hook
sys.excepthook = _handle_uncaught_exceptions

def raise_and_log(message: str, exception_type: type = Exception):
    """
    Log an error and then raise the specified exception.

    :param message: Error message to log and include in the exception.
    :param exception_type: Type of exception to raise (default: Exception).
    """
    l.error(f"Raising exception: {message}")
    raise exception_type(message)

@contextmanager
def catch_and_log(context_info: str = ""):
    """
    Context manager to catch and log exceptions without stopping the program.

    :param context_info: Optional context info to include in the log.
    """
    try:
        yield
    except Exception as e:
        msg = f"Exception caught in context '{context_info}': {e}"
        l.error(msg)
        raise
