import services.message as msg
import services.config as cfg
import services.logger as log
import services.error

l = log.get_logger()
l.debug("Hello World!")
l.info("Info!")
l.warning("Warn!")
l.error("Error!")
l.critical("Critical!!!")

l.info(1/0)
