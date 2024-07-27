# package imports
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By

from pathlib import Path
import re
import pandas as pd
import logging
import traceback

# from joblib import Memory
import requests_cache
from collections import deque
import time
from datetime import datetime
import mimetypes
from pprint import pprint

##### CONSTANTS
OUT_FOLDER = Path.cwd() / "out"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.125 Safari/537.36'}

##### LOGGER SETUP
logging.basicConfig(format='%(asctime)s - %(levelname)s:%(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

#### FUNCTIONS
def create_cache(name="scraper_cache", expire_after=3600*24*14, **kwargs):
    logger.info(f"Creating cache with name {name} which will expire after {expire_after} seconds.")
    requests_cache.install_cache(name, backend='sqlite', expire_after=expire_after, **kwargs)

def clear_cache(name="scraper_cache"):
    requests_cache.clear(name)

def fetch_webpage(url, headers=HEADERS):
    response = requests.get(url, headers=headers)
    response.raise_for_status() # raise exception if response was not successful
    return response

def get_items(bs:BeautifulSoup, parent_url:str, parent=[], is_folder=True)->list[dict]:
    ''' 
    Return a list of dictionaries containing information for each item in the current folder. Items are either documents or folders.
    
    Parameters
    ----------
    bs: BeautifulSoup
        The BeautifulSoup object to parse. Should be the documents site for a website under the civicweb.net domain.
    parent_url : str
        The url of the current folder. This is the url appended onto the root of the website, and should start with "/".
    parent : list(str)
        List of the folders on the path to the current item, relative to the root of the website. parent[0] should be the first folder on the path, and parent[-1] is the current folder. parent=[] indicates that the folder belongs to the root.
    is_folder  : bool
        Whether or not the current folder is a folder (True) or a document (False).

    Returns
    -------
    items : list[dict]
        A list of dictionaries containing information for each item in the current folder. Each dictionary contains the following keys:
        - name : The name of the item.
        - url : The url of the item.
        - parent_url : The url of the parent folder.
        - parent : A list of the folders on the path to the current item.
    '''
    logger.debug("folder parent: %s", parent)

    child_items = []
    if is_folder: 
        item_class = "folder-link" 
    else: 
        item_class = "document-link" 

    for item in bs.find_all("a", class_=item_class):
        item_info = {
                "name": item.text.strip(), 
                "url": item.get('href'),
                "parent": parent,
                "parent_url": parent_url
            }
        logger.debug(f"Found {item_class} with name {item_info['name']} (url: {item_info['url']}) in directory at {'/'.join(item_info['parent'])} (url: {parent_url}).")
        child_items.append(item_info)
    return child_items

def get_filetype(response:requests) -> tuple[str, str]:
    ''' 
    Returns the extension and file type (MIME notation) of a response object based on its Content-Type header.
    '''
    header_mimetype = response.headers['Content-Type']

    # remove mimetype parameter if it exists
    if ";" in header_mimetype:
        header_mimetype = header_mimetype.split(";")[0]
    extension = mimetypes.guess_extension(header_mimetype)

    # raise error if file extension cannot be guessed from response
    if extension is None or extension == "":
        logger.warning("Could not determine file type for response")
        raise TypeError(f"Could not determine file type")
    
    return extension, header_mimetype

def download_file(response:requests, filename:str, out_path=Path.cwd() / "out"):
    ''' 
    Downloads a PDF file from the given response.
    
    Parameters
    ----------
    response : requests.Response
        The response object.
    filename : str
        The name of the file being downloaded. Should include the extension.
    
    out_path : Path, optional
        The path where the file should be saved on the disk, as a pathlib Path object. Defaults to a folder in the current working directory named "out". Does not need to exist.
    '''
    out_path.mkdir(parents=True, exist_ok=True) # ensure directories leading up to the output file path exist
    with open(out_path / filename, "wb") as f:
        f.write(response.content)
        f.close()

##### LOOPS

def find_documents_on_page(folders:deque, done_folders:deque, root_url:str) -> list:
    # breadth-first search to find all subfolders and documents
    documents = []
    while len(folders)>0:
        time.sleep(1)
        logger.debug("folders to visit: %s", "\n".join([str(folder) for folder in folders]))
        logger.debug("completed folders: %s", "\n".join([str(folder) for folder in done_folders]))
        
        curr_folder = folders.popleft()
        logger.info(f"\nSearching folder {curr_folder['name']} at location /{'/'.join(curr_folder['parent'])}...") 
        try:
            response = fetch_webpage(url=root_url+curr_folder["url"])
            bs = BeautifulSoup(response.content,'html.parser')

            # update current folder
            curr_path = curr_folder["parent"].copy()
            curr_path.append(curr_folder["name"])
            logger.debug("currrent folder's parents:%s", curr_folder["parent"])
            logger.debug("current folder's name:%s", curr_folder["name"])
            logger.debug("parent path to add to children folders/documents: %s", curr_path)
            
            # add subfolders to visit from this folder to the folders deque
            # initial_folders = len(folders)
            children_folders = get_items(bs,parent_url=curr_folder["url"], parent=curr_path, is_folder=True)
            folders.extend(children_folders)

            # add documents to download from this folder to the documents list
            # initial_documents = len(documents)
            children_documents = get_items(bs,parent_url=curr_folder["url"], parent=curr_path, is_folder=False)
            documents.extend(children_documents)
            
            logger.info(f"Found {len(children_folders)} folders and {len(children_documents)} documents at this location.")
        except Exception as e:
            tb_str = ''.join(traceback.format_exception(e))
            logger.error(tb_str)
            continue

        done_folders.append(curr_folder)
        curr_path = []
        
        logger.info(f"Completed folder {curr_folder['name']}\n")
    return documents, folders, done_folders

def save_documents(documents, out_folder=OUT_FOLDER):
    rows = []
    for document in documents[:10]:
        error = ""
        file_extension = ""
        try:
            t1 = time.time()
            response = fetch_webpage(url=root_url+document["url"], headers=HEADERS)
            t2 = time.time()
            logger.info((f"Took {round((t2-t1),3)} seconds to get page."))
            out_path = OUT_FOLDER.joinpath(subdomain, *document["parent"])

            file_extension, file_type = get_filetype(response)
            logger.info((f"{document['name']}{file_extension}"))
            download_file(
                response, 
                filename=document["name"]+file_extension,
                out_path=out_path)
        except Exception as e:
            tb_str = ''.join(traceback.format_exception(e))
            logger.error(tb_str)
            error += str(e) # update with error
        finally:
            download_dict = {
                "name": document["name"]+file_extension,
                "file_type": file_type,
                "subdomain": subdomain,
                "parent_path": "/".join(document["parent"]),
                "root_url": root_url, 
                "url": document["url"], 
                "parent_url": document["parent_url"],
                "time_scraped": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "'error_in_scraping'": error,
            }
            rows.append(download_dict)
    return rows