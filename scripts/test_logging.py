
import logging
import sys

# Replicate gateway.py config
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(message)s'))

handlers = [console_handler]
logging.basicConfig(level=logging.DEBUG, handlers=handlers)

logger = logging.getLogger("engine.modes.live")

def test_logging():
    print("Testing stdout print...")
    logger.info("Testing INFO log...")
    logger.debug("Testing DEBUG log (should not see in console)...")
    logger.warning("Testing WARNING log...")

if __name__ == "__main__":
    test_logging()
