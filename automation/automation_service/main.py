"""Entry point for the automation service.

    python -m automation_service.main
    # or, after `pip install -e .`:
    bathroom-automation
"""

from __future__ import annotations

import logging
import signal
import sys

from .config import load_config
from .mqtt_handler import MqttHandler
from .state import StateStore

logger = logging.getLogger("automation_service")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config()
    state = StateStore(config.rule)
    handler = MqttHandler(config, state)

    def handle_shutdown(signum, frame):
        logger.info("received signal %s, shutting down cleanly", signum)
        handler.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    logger.info("connecting to MQTT broker %s:%s", config.mqtt.host, config.mqtt.port)
    handler.connect()
    handler.loop_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
