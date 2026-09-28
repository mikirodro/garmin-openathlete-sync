import requests

class OpenAthleteClient:
    def __init__(self,base_url,email,password):
        self.base_url=base_url.rstrip("/"); self.email=email; self.password=password
        self.s=requests.Session(); self.access=""; self.refresh_token=""
    def login(self):
        r=self.s.post(self.base_url+"/auth/login",json={"email":self.email,"password":self.password},timeout=30); r.raise_for_status()
        d=r.json(); self.access=d["accessToken"]; self.refresh_token=d["refreshToken"]
    def refresh(self):
        r=self.s.post(self.base_url+"/auth/refresh-token",json={"refreshToken":self.refresh_token},timeout=30); r.raise_for_status()
        d=r.json(); self.access=d["accessToken"]; self.refresh_token=d["refreshToken"]
    def create_activity(self,name,start,end,sport,description):
        payload={"type":"ACTIVITY","startDate":start.isoformat(),"endDate":end.isoformat(),"name":(name or "Garmin activity")[:100],"sport":sport,"description":description}
        r=self.s.post(self.base_url+"/event",json=payload,headers={"Authorization":"Bearer "+self.access},timeout=30)
        if r.status_code==401:
            self.refresh(); r=self.s.post(self.base_url+"/event",json=payload,headers={"Authorization":"Bearer "+self.access},timeout=30)
        r.raise_for_status(); return r.json()
