# %%
import json

import httpx
from bs4 import BeautifulSoup


class Scrapper:
    def __init__(self, type="casa"):
        self.type = type
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,ro;q=0.8",
        }
        self.build_id = None
        self.n_pages = None

    def setup(self):
        """Setups the build_id and the number of pages to be scraped"""
        try:
            with httpx.Client(http2=True, headers=self.headers) as client:
             
                response = client.get(
                    f"https://www.storia.ro/ro/rezultate/vanzare/{self.type}/toata-romania?crawl=true&limit=72&view=map"
                )
                response.raise_for_status()

                soup = BeautifulSoup(response.text, "html.parser")
                next_data_script = soup.find("script", id="__NEXT_DATA__")
                
                if next_data_script:
                    full_data = json.loads(next_data_script.string)
                    
                    build_id = full_data.get("buildId")

                    try:
                        listing_data = full_data['props']['pageProps']['tracking']['listing']
                        
                        # set number of pages
                        self.n_pages = listing_data.get('page_count', 1) 
                    except KeyError as e:
                        print(f"Structure change: Could not find key {e}")
                    
                    # set build_id
                    self.build_id = build_id
                    
        except Exception as e:
            print(f"Error:{e}")

    def scrape(self):
        try:
            self.setup()
            with httpx.Client(http2=True, headers=self.headers) as client:
            
                response = client.get(
                    url=f"""https://www.storia.ro/_next/data/{self.build_id}/ro/rezultate/vanzare/{self.type}/toata-romania.json?crawl=true&limit=72&searchingCriteria=vanzare&searchingCriteria=casa&searchingCriteria=toata-romania&page=1"""
                )
                if response.status_code != 200:
                    raise Exception("Error: Unsuccessful request")
            data = json.loads(response.text)
            return data
        except Exception as e:
            print(f"Error:{e}")

    def get_coordinate_map(self):
        """
        Returns a dictionary mapping listing IDs to their (lat, lon).
        Example: {10081559: (44.373, 26.155)}
        """
        map_url = f"https://www.storia.ro/api/v1/listings/map-search/vanzare/{self.type}/toata-romania"
        
        with httpx.Client(headers=self.headers) as client:
            # Note: You may need to pass the same filters/params as your searchget_coordinate_map
            response = client.get(map_url)
            if response.status_code == 200:
                points = response.json() # This is usually a list of small objects
                # Transform list into a lookup dict: {id: (lat, lon)}
                return {item['id']: (item['lat'], item['lon']) for item in points}
        return {}

#%%
s = Scrapper()
s.setup()

#%%
s.scrape()

#%%
with httpx.Client(http2=True, headers=s.headers) as client:
             
    response = client.get(
        f"https://www.storia.ro/ro/rezultate/vanzare/{s.type}/toata-romania?crawl=true&limit=72"
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    next_data_script = soup.find("script", id="__NEXT_DATA__")
    
    if next_data_script:
        full_data = json.loads(next_data_script.string)
        
        build_id = full_data.get("buildId")

#%%
r = s.scrape()

#%%
r.keys()#get('pageProps').get('data').get('searchLinksRelatedLocations')#.get('items')[0]#.keys()#.get('tracking').get('listing').keys()

#%%
r.get('pageProps').keys()

#%%
r.get('pageProps').get('data')
#%%
def get_coordinate_map(self):
    """
    Returns a dictionary mapping listing IDs to their (lat, lon).
    Example: {10081559: (44.373, 26.155)}
    """
    map_url = f"https://www.storia.ro/api/v1/listings/map-search/vanzare/{self.type}/toata-romania"
    
    with httpx.Client(headers=self.headers) as client:
        # Note: You may need to pass the same filters/params as your search
        response = client.get(map_url)
        if response.status_code == 200:
            points = response.json() # This is usually a list of small objects
            # Transform list into a lookup dict: {id: (lat, lon)}
            return {item['id']: (item['lat'], item['lon']) for item in points}
    return {}
#%%
t = s.get_coordinate_map()

#%%
t