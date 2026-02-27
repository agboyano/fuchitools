import logging

def stream_logger(module_name, level="ERROR"):
    logger = logging.getLogger(module_name)
    logger.setLevel(getattr(logging, level)) 

    handler = logging.StreamHandler()
    handler.setLevel(getattr(logging, level))

    logger.addHandler(handler)
    return logger 


