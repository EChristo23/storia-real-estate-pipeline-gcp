#%%
import json
import httpx

_type_map = {
    "casa": "HOUSE",
    "apartament": "APARTMENT",
    "teren": "LAND",
    "garsoniera": "STUDIO",
    "vila": "VILLA"
    }

class GeoScraper:
    def __init__(self, type="casa"):
        self.type = type
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,ro;q=0.8",
            "Content-Type": "application/json",
        }
        self.base_url = "https://www.storia.ro/api/query"
        self.base_geo_dict = {
            "type": "Feature",
            "bbox": [33.2244868411838,49.10398598350171,17.32727012531216,41.98551591590324],
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[33.2244868411838,49.10398598350171],[17.32727012531216,49.10398598350171],[17.32727012531216,41.98551591590324],[33.2244868411838,41.98551591590324],[33.2244868411838,49.10398598350171]]]
            }
        }
        self.base_variables = {
            "clusteringInput":{
                "clusteringAlgorithm":"FIXED_GRID"
                },
            "fetchAdsDetails":False,
            "filterAttributes":{
                "estate":_type_map.get(self.type, "HOUSE"),
                "market":"ALL",
                "ownerTypeSingleSelect":"ALL",
                "transaction":"SELL"
                },
            "filterLocations":{
                "byGeometry":[
                    {
                        "byGeoJson": json.dumps(self.base_geo_dict)
                    }
                ]
            },
            "lang":"RO",
            "page":{"current":1,"limit":36},
            "sortingOption":{"by":"DEFAULT","direction":"DESC"}
        }
        self.operation_name = 'SearchMapPins'
        self.extensions = {"persistedQuery":{"sha256Hash":"51e8703aff1dd9b3ad3bae1ab6c543254e19b3576da1ee23eba0dca2b9341e27","version":1}}
        self.singles = []
        self.clusters = []

    def create_payload(self):
        payload = {
            "operationName": self.operation_name,
            "variables": self.base_variables,
            "extensions": self.extensions,
        }
        return payload
    
    def request(self):
        payload = self.create_payload()
        response = httpx.post(self.base_url, headers=self.headers, json=payload)
        return response.json()
    
    def get_clusters(self, response_json):
        return response_json['data']['searchMapPins']['items'][1]['items']

    def get_singles(self, response_json):
        return response_json['data']['searchMapPins']['items'][0]['items']
    
    def get_bbox(self, cluster):
        lats = [lat[0] for lat in json.loads(cluster.get('shape')).get('coordinates')[0]]
        longs = [long[1] for long in json.loads(cluster.get('shape')).get('coordinates')[0]]
        return [min(lats), min(longs), max(lats), max(longs)]
    
    def get_polygon(self, cluster):
        return json.loads(cluster.get('shape')).get('coordinates')[0]
    
    def update_request(self, cluster):
        new_bbox = self.get_bbox(cluster)
        new_polygon = self.get_polygon(cluster)
        self.base_variables['filterLocations']['byGeometry'][0]['byGeoJson'] = json.dumps({
            "type": "Feature",
            "bbox": new_bbox,
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [new_polygon]
            }
        })
