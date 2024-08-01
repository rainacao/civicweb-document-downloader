# package imports
import requests
from requests_cache import CachedSession

from collections import deque

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException

import pandas as pd
import json
from csv import DictReader
from pathlib import Path
import re
import sys

import time
from datetime import datetime
import logging
import traceback
import pandas as pd
import mimetypes

from pprint import pprint
from tqdm import tqdm

##### CONSTANTS
OUT_FOLDER = Path.cwd() / "out"
OUT_FOLDER.mkdir(exist_ok=True, parents=True)
TRACKING_FOLDER = OUT_FOLDER / "tracking_files"
TRACKING_FOLDER.mkdir(exist_ok=True, parents=True)
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.125 Safari/537.36'}

##### LOGGER SETUP

def logger_setup():
    logging.basicConfig(format='%(asctime)s - %(levelname)s:%(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    return logging.getLogger(__name__)

logger = logger_setup()
# logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)

# logging.basicConfig(format='%(asctime)s - %(levelname)s:%(message)s', datefmt='%Y-%m-%d %H:%M:%S')
# logger = logging.getLogger(__name__)

#### FUNCTIONS
def create_cache(name="test_cache", expire_after=3600*24*14, allowable_codes=[200], **kwargs):
    logger.info(f"Getting cache with name {name} which will expire after {expire_after} seconds.")
    # requests_cache.install_cache(name, backend='sqlite', expire_after=expire_after, **kwargs)
    return CachedSession(name, backend='sqlite', expire_after=expire_after, allowable_codes=allowable_codes, **kwargs)

def remove_url_from_cache(session:CachedSession, urls:list[str]):
    logger.info(f"Removing URLs {urls} from cache {session.cache.cache_name}.")
    session.cache.delete(url=urls)

def clear_cache(session:CachedSession):
    session.cache.clear()

# def fetch_webpage_with_cache(url, session:CachedSession, headers=HEADERS):
#     response = session.get(url, headers=headers)
#     try:
#         response.raise_for_status() # raise exception if response was not successful
#         return response
#     except requests.exceptions.HTTPError as e:
#         raise e

# def fetch_webpage(url, headers=HEADERS):
#     response = requests.get(url, headers=headers)
#     try:
#         response.raise_for_status() # raise exception if response was not successful
#         return response
#     except requests.exceptions.HTTPError as e:
#         raise e

def get_items(response, parent_url:str, parent=[], is_folder=True)->list[dict]:
    ''' 
    Return a list of dictionaries containing information for each item in the current folder. Items are either documents or folders.
    
    Parameters
    ----------
    response: CachedSessions or Requests
        The html object to parse. Should be the documents site for a website under the civicweb.net domain.
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

    bs = BeautifulSoup(response.content,'html.parser')

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
    Downloads a file from the given response.
    
    Parameters
    ----------
    response : requests.Response, cached_requests.CacheSession
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

def download_document(session, document, root_url, subdomain) -> dict:
    error = ""
    file_extension = ""
    file_type = ""

    try:
        response = session.get(url=root_url+document["url"], headers=HEADERS)
        date_scraped = response.created_at.strftime("%Y-%m-%d %H:%M:%S")

        out_path = OUT_FOLDER.joinpath(subdomain, *document["parent"])

        file_extension, file_type = get_filetype(response)
        logger.debug((f"File: {document['name']}{file_extension}"))

        download_file(
            response, 
            filename=document["name"]+file_extension,
            out_path=out_path)
    except Exception as e:
        logger.error(e)
        date_scraped = ""
        error += f"{e}"
        raise e
    finally:
        download_dict = {
                    "name": document["name"]+file_extension,
                    "file_type": file_type,
                    "subdomain": subdomain,
                    "parent_path": "/".join(document["parent"]),
                    "root_url": root_url, 
                    "url": document["url"], 
                    "parent_url": document["parent_url"],
                    "date_scraped": date_scraped,
                    "error": error
                }
        return download_dict

def scrape_site(session, subdomain):
    # breadth-first search to find all subfolders and documents
    logger.info(f"Processing {subdomain}...")
    root_url = f"https://{subdomain}.civicweb.net"

    try:
        # load existing document tracking files if they exist
        with open(TRACKING_FOLDER / f"{subdomain}_documents.csv",'r') as f:
            dict_reader = DictReader(f)
            documents = list(dict_reader)
        logger.info(f"Found existing document tracking file for {subdomain}, {len(documents)} documents long")
    except FileNotFoundError:
        documents = []
    
    try:
        # load existing folder json deques if they exist
        with open(TRACKING_FOLDER / f"{subdomain}_folders.json", "r") as f: 
            json_data = json.load(f)
            folders, done_folders = deque(json_data["folders"]), deque(json_data["done_folders"])

        logger.info(f"Found existing folder tracking file for {subdomain}: {len(done_folders)} folders completed and {len(folders)} to go")
    except FileNotFoundError:
        logger.debug(f"No existing folder tracking file for {subdomain}. Adding root folder to folders as a start.")
        folders = deque([]) 
        done_folders = deque([])

        # get the root url for this subdomain and add the folders at the root to be processed
        try:
            response = session.get(url=root_url+"/filepro/documents/")
            response.raise_for_status()
            folders.extend(get_items(response, parent_url="/filepro/documents/",parent=[], is_folder=True))
        except requests.exceptions.HTTPError as e:
            logger.error(f"Unable to fetch document centre information for {root_url+'/filepro/documents/'} - Code {requests.status_codes}: {e}")
            return 0, False
        except Exception as e:
            logger.error(f"Exception occurred for URL {root_url+'/filepro/documents/'}: {e}")
            return 0, False

    # process all documents on site
    while len(folders)>0:
        time.sleep(1)
        logger.debug("num folders to visit: %s", len([str(folder) for folder in folders]))
        logger.debug("\nnum completed folders: %s", len([str(folder) for folder in done_folders]))
        
        curr_folder = folders.popleft()
        logger.info(f"\nEntering folder {curr_folder['name']} at location \'{subdomain}/{'/'.join(curr_folder['parent'])}\'...") 
        try:
            response = session.get(url=root_url+curr_folder["url"])

            # update current folder's details
            curr_path = curr_folder["parent"].copy()
            curr_path.append(curr_folder["name"])

            logger.debug("parent path to add to children folders/documents: %s", curr_path)
            
            # add subfolders to visit from this folder to the folders deque
            children_folders = get_items(response, parent_url=curr_folder["url"], parent=curr_path, is_folder=True)
            folders.extend(children_folders)

            # add documents to download from this folder
            children_documents = get_items(response, parent_url=curr_folder["url"], parent=curr_path, is_folder=False)

            # download documents
            for document in tqdm(children_documents):
                logger.debug(f"downloading document {document['name']} (URL: {document['url']})")
                download_dict = download_document(session=session, document=document, root_url=root_url, subdomain=subdomain)
                documents.append(download_dict)

            logger.debug(str(documents))
            
        except Exception as e:
            tb_str = ''.join(traceback.format_exception(e))
            logger.error(tb_str)
            continue
        finally:
            # save document information to a csv
            logger.info(f"Updating tracking files for {curr_folder['name']} with {len(children_folders)} new folders and {len(children_documents)} new documents.")

            out_df = pd.DataFrame(documents)
            out_df.to_csv(TRACKING_FOLDER / f"{subdomain}_documents.csv", index=False)

            # save current folder/deque/documents information to a json file
            with open(TRACKING_FOLDER / f"{subdomain}_folders.json", "w") as f:
                json.dump({"folders": list(folders),
                        "done_folders": list(done_folders)}, f, indent=4)

        done_folders.append(curr_folder)
        curr_path = []
        
        logger.info(f"... Exiting folder {curr_folder['name']}.\n")
    logger.info(f"... Found all documents for {subdomain}.\n\n")
    return len(documents), True

if __name__ == "__main__":
    # start cache
    session = create_cache(
        name="test_cache", 
        expire_after=3600*24*14, 
        allowable_codes=[200] # only save successful requests
        )
    
    # load existing subdomain information 
    try:
        subdomains_dict = json.load(open(f"{OUT_FOLDER}/subdomains.json"))
        logger.info(f"Loaded in existing subdomains.json file.")
    except:
        subdomains_dict = {}
        logger.info(f"No existing subdomains.json file found in the {OUT_FOLDER} folder.")

    # for subdomain in subdomains_dict.keys():
    subdomains_to_scrape = [subdomain
                        for subdomain in subdomains_dict.keys() 
                        if "complete" not in subdomains_dict[subdomain] or subdomains_dict[subdomain]["complete"] == False]
    
    # for subdomain in subdomains_to_scrape:
    for subdomain in ["victoria", "winchesterva"]:
        # scrape the site
        num_documents, scrape_completness = scrape_site(session, subdomain)

        # track different information
        subdomains_dict[subdomain]["document_count"] = num_documents
        subdomains_dict[subdomain]["complete"] = scrape_completness
        logger.info(f"{subdomain} has {num_documents} documents.")

        with open(f"{OUT_FOLDER}/subdomains.json", "w") as f:
            json.dump(subdomains_dict, f, indent=4)