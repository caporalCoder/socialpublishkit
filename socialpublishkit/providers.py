"""Official social-network video adapters, originally extracted from Algovid.

The public English API is exposed by socialpublishkit.Publisher. Legacy French
adapter/account-store names are retained for Algovid interoperability. No app
credentials or account tokens are bundled in this package.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

GRAPH = "https://graph.facebook.com/v26.0"
RUPLOAD = "https://rupload.facebook.com"
TIKTOK = "https://open.tiktokapis.com"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
MARGE = 120                     # secondes : un jeton qui expire bientôt est renouvelé avant l'envoi
ATTENTE = 15                    # secondes entre deux lectures de l'état d'une vidéo
LECTURES = 40                   # soit 10 minutes au plus
MORCEAU = 10 << 20              # octets par morceau pour TikTok (de 5 à 64 Mo)
MODES_TIKTOK = {"brouillon": "Brouillon à finir dans TikTok", "prive": "Privé (compte privé)",
                "public": "Public (application auditée)"}


class ErreurReseau(RuntimeError):
    """Un réseau a refusé. passagere : un nouvel essai a des chances de marcher."""

    def __init__(self, message: str, passagere: bool = False):
        super().__init__(message)
        self.passagere = passagere


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


# Never forward OAuth headers, codes, tokens or video bytes through redirects.
_open = urllib.request.build_opener(_NoRedirect()).open


def _http(methode: str, url: str, corps: bytes | None = None, entetes: dict | None = None,
          delai: float = 300) -> tuple[int, dict, bytes]:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ErreurReseau("Provider endpoints must use HTTPS without embedded credentials or fragments")
    requete = urllib.request.Request(url, data=corps, method=methode, headers=entetes or {})
    try:
        with _open(requete, timeout=delai) as r:
            body = r.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise ErreurReseau("Provider response exceeds the supported size")
            return r.status, dict(r.headers), body
    except urllib.error.HTTPError as e:
        code = e.code
        e.close()
        raise ErreurReseau(f"Provider HTTP error {code}", code == 429 or code >= 500) from None
    except (urllib.error.URLError, OSError):
        raise ErreurReseau("Provider connection failed", True) from None


def _json(methode: str, url: str, corps: bytes | None = None, entetes: dict | None = None) -> dict:
    return json.loads(_http(methode, url, corps, entetes)[2] or b"{}")


def _formulaire(url: str, champs: dict, entetes: dict | None = None) -> dict:
    return _json("POST", url, urllib.parse.urlencode(champs).encode(),
                 {"Content-Type": "application/x-www-form-urlencoded", **(entetes or {})})


class Reseau:
    cle = titre = compte_requis = portail = redirection = ""
    variables: tuple[str, ...] = ()
    connexion = ""                     # le réseau dont la connexion sert aussi à celui-ci

    def __init__(self, racine: str = "", *, config: dict | None = None, redirect_uri: str | None = None):
        self.racine = racine
        self.config = dict(config) if config is not None else None
        self.on_refresh = None
        if redirect_uri is not None:
            self.redirection = redirect_uri

    def valeur(self, nom: str) -> str:
        """Une clé de .env, relu à chaque fois : la coller ne demande pas de redémarrer."""
        if self.config is not None:
            return self.config.get(nom, "")
        try:
            with open(os.path.join(self.racine, ".env"), encoding="utf-8") as f:
                for ligne in f:
                    m = re.match(rf"\s*(?:export\s+)?{nom}\s*=\s*(.+?)\s*$", ligne)
                    if m:
                        return m[1].strip("\"'")
        except OSError:
            pass
        return os.environ.get(nom, "")

    def configure(self) -> bool:
        return all(self.valeur(v) for v in self.variables)


class YouTube(Reseau):
    cle, titre = "youtube", "YouTube"
    variables = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
    redirection = "http://localhost/oauth/youtube"
    portail = "https://console.cloud.google.com/apis/credentials"
    compte_requis = "Une chaîne YouTube. Sans audit de Google, les vidéos restent privées."
    PORTEES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"

    def adresse(self, etat: str) -> str:
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": self.valeur("GOOGLE_CLIENT_ID"), "redirect_uri": self.redirection, "response_type": "code",
            "scope": self.PORTEES, "access_type": "offline", "prompt": "consent", "state": etat})

    def connecter(self, code: str) -> dict:
        t = _formulaire(GOOGLE_TOKEN, {"code": code, "client_id": self.valeur("GOOGLE_CLIENT_ID"),
                                       "client_secret": self.valeur("GOOGLE_CLIENT_SECRET"),
                                       "redirect_uri": self.redirection, "grant_type": "authorization_code"})
        chaines = _json("GET", "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                        entetes={"Authorization": f"Bearer {t['access_token']}"}).get("items", [])
        nom = chaines[0]["snippet"]["title"] if chaines else "Chaîne YouTube"
        return {"youtube": {"nom": nom, "channel_id": chaines[0]["id"] if chaines else "", "jeton": t["access_token"], "renouvellement": t.get("refresh_token"),
                            "expire": time.time() + t.get("expires_in", 3600)}}

    def _jeton(self, compte: dict) -> str:
        if time.time() > compte["expire"] - MARGE:
            t = _formulaire(GOOGLE_TOKEN, {"refresh_token": compte["renouvellement"], "grant_type": "refresh_token",
                                           "client_id": self.valeur("GOOGLE_CLIENT_ID"),
                                           "client_secret": self.valeur("GOOGLE_CLIENT_SECRET")})
            compte |= {"jeton": t["access_token"], "expire": time.time() + t.get("expires_in", 3600)}
            if self.on_refresh:
                self.on_refresh(compte)
        return compte["jeton"]

    def publier(self, compte: dict, video: str, texte: dict, options: dict) -> dict:
        taille = os.path.getsize(video)
        jeton = self._jeton(compte)
        settings = options.get("youtube", {})
        snippet = {"title": texte["titre"], "description": texte["description"], "tags": texte["tags"]}
        if settings.get("category_id"):
            snippet["categoryId"] = settings["category_id"]
        if settings.get("language"):
            snippet["defaultLanguage"] = settings["language"]
        fiche = {"snippet": snippet,
                 "status": {"privacyStatus": settings.get("privacy", "private"),
                            "selfDeclaredMadeForKids": settings.get("made_for_kids", False)}}
        _, entetes, _ = _http("POST", "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                              json.dumps(fiche).encode(),
                              {"Authorization": f"Bearer {jeton}", "Content-Type": "application/json; charset=UTF-8",
                               "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(taille)})
        adresse = {k.lower(): v for k, v in entetes.items()}.get("location")
        if not adresse:
            raise ErreurReseau("YouTube n'a pas donné d'adresse d'envoi")
        with open(video, "rb") as f:
            reponse = _http("PUT", adresse, f.read(), {"Content-Type": "video/mp4"}, delai=1800)[2]
        id_ = json.loads(reponse)["id"]
        return {"id": id_, "status": "uploaded", "url": f"https://www.youtube.com/watch?v={id_}",
                "note": "Vidéo reçue. Traitement et visibilité à vérifier ; elle peut rester privée sans audit Google."}


class TikTok(Reseau):
    cle, titre = "tiktok", "TikTok"
    variables = ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET")
    redirection = "http://localhost/oauth/tiktok"
    portail = "https://developers.tiktok.com/apps"
    compte_requis = "Brouillon à terminer dans TikTok. L'application et le compte doivent autoriser video.upload."
    PORTEES = "user.info.basic,video.upload"

    def portees(self) -> str:
        return self.valeur("TIKTOK_SCOPES") or self.PORTEES

    def modes(self) -> dict:
        portees = {p.strip() for p in self.portees().split(",")}
        return {k: v for k, v in MODES_TIKTOK.items()
                if ("video.upload" if k == "brouillon" else "video.publish") in portees}

    def adresse(self, etat: str) -> str:
        return "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
            "client_key": self.valeur("TIKTOK_CLIENT_KEY"), "redirect_uri": self.redirection, "response_type": "code",
            "scope": self.portees(), "state": etat})

    def _jetons(self, champs: dict) -> dict:
        t = _formulaire(f"{TIKTOK}/v2/oauth/token/", {"client_key": self.valeur("TIKTOK_CLIENT_KEY"),
                                                      "client_secret": self.valeur("TIKTOK_CLIENT_SECRET"), **champs})
        if "access_token" not in t:
            raise ErreurReseau(f"TikTok a refusé : {t.get('error_description') or t.get('error') or t}")
        return {"jeton": t["access_token"], "renouvellement": t.get("refresh_token"),
                "open_id": t.get("open_id", ""), "scope": t.get("scope", ""),
                "expire": time.time() + t.get("expires_in", 86400)}

    def connecter(self, code: str) -> dict:
        c = self._jetons({"code": code, "grant_type": "authorization_code", "redirect_uri": self.redirection})
        u = _json("GET", f"{TIKTOK}/v2/user/info/?fields=display_name", entetes={"Authorization": f"Bearer {c['jeton']}"})
        return {"tiktok": {"nom": u.get("data", {}).get("user", {}).get("display_name", "Compte TikTok"), **c}}

    def _appel(self, chemin: str, corps: dict, jeton: str) -> dict:
        d = _json("POST", f"{TIKTOK}{chemin}", json.dumps(corps).encode(),
                  {"Authorization": f"Bearer {jeton}", "Content-Type": "application/json; charset=UTF-8"})
        code = d.get("error", {}).get("code", "ok")
        if code != "ok":
            raise ErreurReseau(f"TikTok : {code} : {d['error'].get('message', '')}", code == "rate_limit_exceeded")
        return d["data"]

    def publier(self, compte: dict, video: str, texte: dict, options: dict) -> dict:
        mode = options.get("tiktok", "brouillon")
        if mode not in self.modes():
            raise ErreurReseau("Ce mode TikTok n'est pas activé pour cette application. Utilise le brouillon.")
        if time.time() > compte["expire"] - MARGE:
            compte |= self._jetons({"grant_type": "refresh_token", "refresh_token": compte["renouvellement"]})
            if self.on_refresh:
                self.on_refresh(compte)
        taille = os.path.getsize(video)
        if not taille:
            raise ErreurReseau("La vidéo est vide.")
        morceau = taille if taille <= MORCEAU else MORCEAU
        nombre = taille // morceau
        source = {"source": "FILE_UPLOAD", "video_size": taille, "chunk_size": morceau, "total_chunk_count": nombre}
        if mode == "brouillon":
            d = self._appel("/v2/post/publish/inbox/video/init/", {"source_info": source}, compte["jeton"])
        else:
            creator = self._appel("/v2/post/publish/creator_info/query/", {}, compte["jeton"])
            privacy = "SELF_ONLY" if mode == "prive" else "PUBLIC_TO_EVERYONE"
            if privacy not in creator.get("privacy_level_options", []):
                raise ErreurReseau("Cette visibilité TikTok n'est pas autorisée pour ce compte.")
            duration = options.get("duration_seconds")
            if duration is not None and duration > creator.get("max_video_post_duration_sec", 0):
                raise ErreurReseau("La vidéo dépasse la durée autorisée par TikTok.")
            prive = {"title": texte["texte"], "privacy_level": privacy,
                     "brand_content_toggle": options.get("paid_partnership", False),
                     "brand_organic_toggle": options.get("own_brand", False)}
            for kind in ("comment", "duet", "stitch"):
                prive[f"disable_{kind}"] = bool(creator.get(f"{kind}_disabled") or
                                               options.get(f"disable_{kind}", True))
            if options.get("ai_generated") is not None:
                prive["is_aigc"] = options["ai_generated"]
            d = self._appel("/v2/post/publish/video/init/", {"post_info": prive, "source_info": source}, compte["jeton"])
        with open(video, "rb") as f:
            for k in range(nombre):
                debut = k * morceau
                fin = taille - 1 if k == nombre - 1 else debut + morceau - 1
                f.seek(debut)
                _http("PUT", d["upload_url"], f.read(fin - debut + 1), {
                    "Content-Type": "video/mp4", "Content-Range": f"bytes {debut}-{fin}/{taille}"}, delai=900)
        for _ in range(LECTURES):
            s = self._appel("/v2/post/publish/status/fetch/", {"publish_id": d["publish_id"]}, compte["jeton"])
            if s.get("status") == "FAILED":
                raise ErreurReseau(f"TikTok : {s.get('fail_reason')}")
            if s.get("status") == "SEND_TO_USER_INBOX":
                return {"id": d["publish_id"], "status": "draft_delivered", "url": "", "note": f"Brouillon reçu : le texte à coller est prêt. Finis-le dans TikTok : {texte['texte'][:80]}"}
            if s.get("status") == "PUBLISH_COMPLETE":
                return {"id": d["publish_id"], "status": "published", "url": "", "note": "Publiée" if mode == "public" else "Publiée en privé."}
            time.sleep(ATTENTE)
        raise ErreurReseau("TikTok n'a pas fini de traiter la vidéo en 10 minutes : à vérifier dans l'application")


class Facebook(Reseau):
    cle, titre = "facebook", "Facebook"
    variables = ("META_APP_ID", "META_APP_SECRET")
    redirection = "http://localhost/oauth/facebook"
    portail = "https://developers.facebook.com/apps"
    compte_requis = "Une Page Facebook, pas un profil personnel."
    PORTEES = "pages_show_list,pages_read_engagement,pages_manage_posts"

    def adresse(self, etat: str) -> str:
        return "https://www.facebook.com/v26.0/dialog/oauth?" + urllib.parse.urlencode({
            "client_id": self.valeur("META_APP_ID"), "redirect_uri": self.redirection, "state": etat,
            "scope": self.PORTEES, "response_type": "code"})

    def connecter(self, code: str) -> dict:
        secret = {"client_id": self.valeur("META_APP_ID"), "client_secret": self.valeur("META_APP_SECRET")}
        court = _formulaire(f"{GRAPH}/oauth/access_token", {**secret, "redirect_uri": self.redirection, "code": code})
        long_ = _formulaire(f"{GRAPH}/oauth/access_token", {**secret, "grant_type": "fb_exchange_token",
                                                            "fb_exchange_token": court["access_token"]})
        entete = {"Authorization": f"Bearer {long_['access_token']}"}
        pages = _json("GET", f"{GRAPH}/me/accounts?fields=id,name,access_token",
                      entetes=entete).get("data", [])
        voulue = self.valeur("META_PAGE_ID")
        pages = [p for p in pages if not voulue or p["id"] == voulue]
        if not pages:
            raise ErreurReseau("Aucune Page Facebook trouvée sur ce compte : l'API ne publie que sur une Page.")
        if len(pages) > 1:
            raise ErreurReseau("Plusieurs Pages autorisées : choisis une seule Page dans Meta ou renseigne META_PAGE_ID.")
        page = pages[0]
        return {"facebook": {"nom": page["name"], "page": page["id"], "jeton": page["access_token"]}}

    def publier(self, compte: dict, video: str, texte: dict, options: dict) -> dict:
        entete = {"Authorization": f"Bearer {compte['jeton']}"}
        adresse = f"{GRAPH}/{compte['page']}/video_reels"
        id_ = _formulaire(adresse, {"upload_phase": "start"}, entete)["video_id"]
        with open(video, "rb") as f:
            contenu = f.read()
        _http("POST", f"{RUPLOAD}/video-upload/{id_}", contenu, {
            "Authorization": f"OAuth {compte['jeton']}", "offset": "0", "file_size": str(len(contenu)),
            "Content-Type": "application/octet-stream"}, delai=900)
        _formulaire(adresse, {"upload_phase": "finish", "video_id": id_, "video_state": "PUBLISHED",
                              "description": texte["texte"]}, entete)
        for _ in range(LECTURES):
            s = _json("GET", f"{GRAPH}/{id_}?fields=status", entetes=entete).get("status", {})
            if s.get("video_status") in ("error", "upload_failed", "expired"):
                raise ErreurReseau(f"Facebook : {s}")
            if s.get("publishing_phase", {}).get("status") == "complete":
                return {"id": id_, "status": "published", "url": f"https://www.facebook.com/reel/{id_}", "note": ""}
            time.sleep(ATTENTE)
        raise ErreurReseau("Facebook n'a pas fini de traiter la vidéo en 10 minutes : à vérifier sur la Page")


class Instagram(Reseau):
    cle, titre = "instagram", "Instagram"
    variables = (*Facebook.variables, "INSTAGRAM_CONFIG_ID")
    redirection = "http://localhost/oauth/instagram"
    portail = Facebook.portail
    compte_requis = "Un compte Instagram Créateur ou Business dans un portefeuille Meta. Connexion Instagram, sans Page Facebook."

    def adresse(self, etat: str) -> str:
        # prompt=login affiche le choix Instagram même si Facebook est déjà connecté.
        # Les permissions sont définies par la configuration Unified Login, pas par scope.
        return "https://www.facebook.com/dialog/oauth?" + urllib.parse.urlencode({
            "client_id": self.valeur("META_APP_ID"), "config_id": self.valeur("INSTAGRAM_CONFIG_ID"),
            "redirect_uri": self.redirection, "response_type": "code", "override_default_response_type": "true",
            "prompt": "login", "state": etat})

    def connecter(self, code: str) -> dict:
        # Unified Login renvoie un Business Integration System User Access Token.
        # /me n'est donc pas le compte Instagram : lire les comptes attribués, jamais les Pages.
        params = urllib.parse.urlencode({"client_id": self.valeur("META_APP_ID"),
            "client_secret": self.valeur("META_APP_SECRET"), "redirect_uri": self.redirection, "code": code})
        try:
            t = _json("GET", f"{GRAPH}/oauth/access_token?{params}")
        except ErreurReseau as e:
            # L'endpoint officiel exige le secret dans la requête serveur : ne jamais le
            # recopier dans le message de retour OAuth ou une erreur réseau.
            raise ErreurReseau("Instagram : échange du code refusé. Recommence la connexion.", e.passagere) from None
        if not t.get("access_token"):
            raise ErreurReseau("Instagram n'a pas renvoyé de jeton. Recommence la connexion.")
        entete = {"Authorization": f"Bearer {t['access_token']}"}
        business = _json("GET", f"{GRAPH}/me?fields=client_business_id", entetes=entete)
        comptes, curseur, vus = [], "", set()
        while True:
            params = urllib.parse.urlencode({"fields": "id,username", "limit": 100, **({"after": curseur} if curseur else {})})
            page = _json("GET", f"{GRAPH}/me/assigned_instagram_accounts?{params}", entetes=entete)
            comptes.extend(page.get("data", []))
            suite = page.get("paging", {})
            curseur = suite.get("cursors", {}).get("after")
            if not suite.get("next"):
                break
            if not curseur or curseur in vus or len(vus) >= 100:
                raise ErreurReseau("Instagram : liste des comptes incomplète. Autorise un seul compte puis reconnecte-toi.")
            vus.add(curseur)
        voulu = self.valeur("INSTAGRAM_ACCOUNT_ID")
        comptes = {str(c["id"]): c for c in comptes if not voulu or str(c["id"]) == voulu}
        if not comptes:
            raise ErreurReseau("Aucun compte Instagram autorisé ne correspond. Choisis un compte Créateur ou Business dans Meta et vérifie INSTAGRAM_ACCOUNT_ID.")
        if len(comptes) > 1:
            raise ErreurReseau("Plusieurs comptes Instagram autorisés : choisis-en un seul dans Meta ou renseigne INSTAGRAM_ACCOUNT_ID.")
        ig = next(iter(comptes.values()))
        compte = {"nom": ig.get("username") or str(ig["id"]), "ig": str(ig["id"]),
                  "jeton": t["access_token"], "connexion": "instagram_unified",
                  "business": business.get("client_business_id")}
        if t.get("expires_in"):
            compte["expire"] = time.time() + int(t["expires_in"])
        return {"instagram": compte}

    def publier(self, compte: dict, video: str, texte: dict, options: dict) -> dict:
        if compte.get("expire") and time.time() >= compte["expire"] - MARGE:
            raise ErreurReseau("La connexion Instagram a expiré : reconnecte le compte depuis Planning.")
        entete = {"Authorization": f"Bearer {compte['jeton']}"}
        conteneur = _formulaire(f"{GRAPH}/{compte['ig']}/media", {
            "media_type": "REELS", "upload_type": "resumable", "caption": texte["texte"], "share_to_feed": "true"}, entete)["id"]
        with open(video, "rb") as f:
            contenu = f.read()
        _http("POST", f"{RUPLOAD}/ig-api-upload/v26.0/{conteneur}", contenu, {
            "Authorization": f"OAuth {compte['jeton']}", "offset": "0", "file_size": str(len(contenu))}, delai=900)
        for _ in range(LECTURES):
            code = _json("GET", f"{GRAPH}/{conteneur}?fields=status_code", entetes=entete).get("status_code")
            if code == "FINISHED":
                break
            if code in ("ERROR", "EXPIRED"):
                raise ErreurReseau(f"Instagram : {code}")
            time.sleep(ATTENTE)
        else:
            raise ErreurReseau("Instagram n'a pas fini de traiter la vidéo en 10 minutes")
        media = _formulaire(f"{GRAPH}/{compte['ig']}/media_publish", {"creation_id": conteneur}, entete)["id"]
        lien = _json("GET", f"{GRAPH}/{media}?fields=permalink", entetes=entete).get("permalink", "")
        return {"id": media, "status": "published", "url": lien, "note": ""}


RESEAUX = (Facebook, Instagram, YouTube, TikTok)


class Comptes:
    """Les comptes connectés. Leurs jetons ne sortent jamais d'ici vers la page."""

    def __init__(self, racine: str):
        self.racine = racine
        self.chemin = os.path.join(racine, "runs", "interface", "comptes.json")
        self.verrou = threading.Lock()
        self.reseaux = {r.cle: r(racine) for r in RESEAUX}

    def lire(self) -> dict:
        try:
            with open(self.chemin, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _ecrire(self, comptes: dict):
        os.makedirs(os.path.dirname(self.chemin), exist_ok=True)
        tmp = f"{self.chemin}.{os.getpid()}.tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
            json.dump(comptes, f)
        os.replace(tmp, self.chemin)

    def enregistrer(self, nouveaux: dict):
        with self.verrou:
            self._ecrire(self.lire() | nouveaux)

    def oublier(self, cle: str):
        with self.verrou:
            comptes = self.lire()
            comptes.pop(cle, None)
            if cle == "facebook" and comptes.get("instagram", {}).get("connexion") != "instagram_unified":
                # Anciennes connexions seulement : un compte Unified est indépendant.
                comptes.pop("instagram", None)
            self._ecrire(comptes)

    def publier(self, cle: str, video: str, texte: dict, options: dict) -> dict:
        compte = self.lire().get(cle)
        if compte is None:
            raise ErreurReseau(f"{self.reseaux[cle].titre} n'est plus connecté")
        resultat = self.reseaux[cle].publier(compte, video, texte, options)
        self.enregistrer({cle: compte})        # un jeton a pu être renouvelé pendant l'envoi
        return resultat

    def resume(self) -> list[dict]:
        comptes = self.lire()
        return [{"cle": r.cle, "titre": r.titre, "connexion": r.connexion or r.cle, "configure": r.configure(),
                 "nom": comptes.get(r.cle, {}).get("nom"), "variables": r.variables, "portail": r.portail,
                 "requis": r.compte_requis, "redirection": self.reseaux[r.connexion or r.cle].redirection}
                for r in self.reseaux.values()]
