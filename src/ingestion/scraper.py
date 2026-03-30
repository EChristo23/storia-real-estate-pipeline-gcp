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
            client = httpx.Client(http2=True, headers=self.headers)
            response = client.get(
                f"https://www.storia.ro/ro/rezultate/vanzare/{self.type}/toata-romania?crawl=true&limit=72"
            )
            soup = BeautifulSoup(response.text, "html.parser")
            next_data_script = soup.find("script", id="__NEXT_DATA__")
            if next_data_script:
                print("has Next Data")
                full_data = json.loads(next_data_script.string)
                print(full_data.keys())
                build_id = full_data.get("buildId")
                n_pages = (
                    full_data.get("props")
                    .get("pageProps")
                    .get("tracking")
                    .get("listing")
                    .get("page_count")
                )
                self.build_id = build_id
                self.n_pages = n_pages
        except Exception as e:
            print(f"Error:{e}")

    def scrape(self):
        client = httpx.Client(http2=True, headers=self.headers)
        response = client.get(
            url=f"""https://www.storia.ro/_next/data/{self.build_id}/ro/rezultate/vanzare/{self.type}/toata-romania.json?crawl=true&limit=72&searchingCriteria=vanzare&searchingCriteria=casa&searchingCriteria=toata-romania&page=1"""
        )
        if response.status_code != 200:
            raise Exception("Error: Unsuccessful request")
        data = json.loads(response.text)
        return data
