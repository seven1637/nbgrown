
import logging
logger = logging.getLogger('nbgrown')  
logger.setLevel(logging.DEBUG)  
fh = logging.FileHandler(r'/nbgrown/log/user_log.log')  
fh.setLevel(logging.DEBUG)  
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')  
fh.setFormatter(formatter)  
logger.addHandler(fh)  
DEBUG_LOG = logger.debug
ERROR_LOG = logger.error
