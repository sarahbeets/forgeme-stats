#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Préparation mensuelle à partir des exports Metricool (marque FORGE ME).

  requetes AAAA-MM [--jusqu-au AAAA-MM-JJ]
      Affiche, pour chaque fichier attendu, la période et la liste exacte des métriques
      à demander (dans cet ordre). --jusqu-au arrête la période avant la fin du mois
      (mois en cours).

  preparer AAAA-MM --brut DOSSIER --sortie FICHIER.json [--jusqu-au AAAA-MM-JJ]
      Lit dans DOSSIER les réponses Metricool enregistrées telles quelles
      (un fichier par requête : facebook.json, instagram.json, ...), calcule les
      indicateurs du mois et écrit un mois prêt à compléter : chiffres, courbes jour par
      jour, classements de posts, reels et campagnes, et textes marqués « À RÉDIGER ».
      Si FM_MOT_DE_PASSE est défini, affiche aussi la comparaison avec le mois précédent.

  actualiser AAAA-MM --brut DOSSIER --sortie FICHIER.json [--jusqu-au AAAA-MM-JJ]
      Pour un mois déjà rédigé : reprend les chiffres frais de DOSSIER (organique et publicité),
      garde les textes et les titres déjà écrits, et liste ce qui a changé pour mettre les textes
      à jour. Demande FM_MOT_DE_PASSE.

Les installations, résultats et vues vidéo de la publicité viennent des campagnes Metricool.
Les chiffres relevés à la main dans les gestionnaires de publicités peuvent compléter le fichier du mois.
"""
import argparse
import calendar
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from commun import config  # noqa: E402

A_REDIGER = "À RÉDIGER"
FORMATS_IG = {"FEED_IMAGE": "Image", "FEED_CAROUSEL_ALBUM": "Carrousel", "FEED_VIDEO": "Vidéo",
              "REELS": "Reel", "CAROUSEL_ALBUM": "Carrousel", "IMAGE": "Image", "VIDEO": "Vidéo"}


def periode(mois: str, fuseau: str, jusqua: str = None):
    an, m = (int(x) for x in mois.split("-"))
    dernier = calendar.monthrange(an, m)[1]
    if jusqua:
        ja, jm, jj = (int(x) for x in jusqua.split("-"))
        if (ja, jm) != (an, m) or not 1 <= jj <= dernier:
            sys.exit("--jusqu-au doit tomber dans le mois %s." % mois)
        dernier = jj
    tz = ZoneInfo(fuseau)
    debut = datetime(an, m, 1, 0, 0, 0, tzinfo=tz)
    fin = datetime(an, m, dernier, 23, 59, 59, tzinfo=tz)
    return debut.isoformat(), fin.isoformat()


def num(x):
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def charger(dossier: Path, nom: str, metriques):
    f = dossier / (nom + ".json")
    if not f.exists():
        return None
    brut = json.loads(f.read_text(encoding="utf-8"))
    lignes = brut.get("rows", brut) if isinstance(brut, dict) else brut
    for ligne in lignes:
        if len(ligne) > len(metriques) + 1:
            sys.exit("%s : une ligne compte %d valeurs pour %d métriques demandées." % (f.name, len(ligne), len(metriques)))
    return lignes


def evolution(lignes, metriques):
    """Lignes quotidiennes : [m1, m2, ..., AAAAMMJJ]. Renvoie des accès somme / dernière / unique."""
    lignes = sorted(lignes, key=lambda l: str(l[-1]))
    col = {m: i for i, m in enumerate(metriques)}

    def somme(m):
        vals = [num(l[col[m]]) for l in lignes]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None

    def derniere(m):
        for l in reversed(lignes):
            v = num(l[col[m]])
            if v is not None:
                return v
        return None
    return somme, derniere


def entier(v):
    return None if v is None else int(round(v))


def arrondi(v, d=2):
    return None if v is None else round(v, d)


def titre_par_defaut(texte, limite=70):
    premiere = (texte or "").strip().split("\n")[0].strip()
    return premiere if len(premiere) <= limite else premiere[:limite - 1].rstrip() + "…"


def date_iso(v):
    v = str(v)
    return "%s-%s-%s" % (v[0:4], v[4:6], v[6:8]) if len(v) >= 8 and v[:8].isdigit() else v


MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre"]


def jour_mois(iso):
    an, m, j = iso.split("-")
    return "%s %s" % ("1er" if j == "01" else str(int(j)), MOIS_FR[int(m) - 1])


def kpis_facebook(lignes, met):
    s, d = evolution(lignes, met)
    k = {
        "followers": entier(d("FBEV17")), "followersGained": entier(s("FBEV47")), "followersLost": entier(s("FBEV48")),
        "posts": entier(s("FBEV04")), "reels": entier(s("FBEV21")), "stories": entier(s("FBEV35")),
        "views": entier(s("FBEV49")), "pageVisits": entier(s("FBEV03")),
        "avgReachPerPost": arrondi(d("FBEV18"), 1), "engagement": arrondi(d("FBEV19"), 2),
        "interactions": entier(s("FBEV34")), "clicks": entier(s("FBEV16")), "reactions": entier(s("FBEV13")),
        "comments": entier(s("FBEV14")), "shares": entier(s("FBEV15")),
    }
    k["contents"] = sum(v or 0 for v in (k["posts"], k["reels"], k["stories"]))
    return {a: b for a, b in k.items() if b is not None}


def kpis_instagram(lignes, met, plus=None, met_plus=None):
    """Indicateurs Instagram. « plus » apporte la portée du compte, les reels, les stories et les comptes engagés.

    Les posts du fil (photos, carrousels) et les reels sont comptés à part chez Metricool : les indicateurs
    propres aux posts ne sont gardés que s'il y a eu des posts dans le mois.
    """
    s, d = evolution(lignes, met)
    lignes_triees = sorted(lignes, key=lambda l: str(l[-1]))
    col = met.index("IGEV01")
    abonnes = [(str(l[-1]), num(l[col])) for l in lignes_triees if num(l[col]) is not None]
    posts, reels, stories = entier(s("IGEV04")) or 0, entier(s("IGEV22")) or 0, entier(s("IGEV16")) or 0
    gagnes, perdus = entier(s("IGEV43")), entier(s("IGEV44"))
    k = {"followers": entier(d("IGEV01")), "views": entier(s("IGEV05"))}
    if gagnes or perdus:
        # Instagram ne donne ces deux chiffres qu'à partir de 100 abonnés
        k["followersGained"], k["followersLost"] = gagnes, perdus
        k["netFollowers"] = (gagnes or 0) - (perdus or 0)
    elif len(abonnes) >= 2:
        k["netFollowers"] = entier(abonnes[-1][1] - abonnes[0][1])
    k["posts"], k["reels"] = posts, reels
    if stories:
        k["stories"] = stories
    k["contents"] = posts + reels + stories
    if posts:
        k.update({"avgReachPerPost": arrondi(d("IGEV19"), 1), "engagement": arrondi(d("IGEV21"), 2),
                  "interactions": entier(s("IGEV09")), "likes": entier(s("IGEV13")), "comments": entier(s("IGEV14")),
                  "shares": entier(s("IGEV40")), "saves": entier(s("IGEV15"))})
    if stories:
        k["avgReachPerStory"] = arrondi(d("IGEV20"), 1)
    if reels:
        k["reelsAvgReach"] = arrondi(d("IGEV30"), 0)
        k["reelsViews"] = entier(s("IGEV23"))
    if plus and met_plus:
        sp, dp = evolution(plus, met_plus)
        portee = sp("IGEV06")
        if portee:
            jours = len({str(l[-1]) for l in plus})
            k["reachTotal"] = entier(portee)
            k["reachPerDay"] = arrondi(portee / max(jours, 1), 2)
        if reels:
            k["reelsInteractions"] = entier(sp("IGEV25"))
            k["reelsEngagement"] = arrondi(dp("IGEV31"), 2)
        if stories and sp("IGEV17"):
            k["storyImpressions"] = entier(sp("IGEV17"))
        if sp("IGEV42"):
            k["accountsEngaged"] = entier(sp("IGEV42"))
    return {a: b for a, b in k.items() if b is not None}


def serie_jour(lignes, met, cle):
    """Courbe jour par jour d'un indicateur cumulé (abonnés) : [["AAAA-MM-JJ", valeur], ...]."""
    col = met.index(cle)
    out = []
    for l in sorted(lignes or [], key=lambda l: str(l[-1])):
        v = num(l[col])
        if v is not None:
            out.append([date_iso(l[-1]), entier(v)])
    return out if len(out) >= 2 else None


def nom_campagne(nom):
    """Nom affiché d'une campagne : celui choisi dans config.json, sinon sans « BROUILLON » ni montant en fin de nom."""
    nom = (nom or "").strip()
    choix = config()["metricool"].get("noms_campagnes", {})
    if nom in choix:
        return choix[nom]
    garde = [x.strip() for x in nom.split("/")]
    garde = [x for x in garde if x.upper() != "BROUILLON" and not re.fullmatch(r"[\d\s.,]+\s*(EUR|€)", x, re.I)]
    return " / ".join(garde) or nom


def kpis_publicite(lignes, met):
    s, d = evolution(lignes, met)

    def couts(impr, clics, dep):
        out = {}
        if impr:
            out["cpm"] = round(dep / impr * 1000, 2)
            out["ctr"] = round(clics / impr * 100, 2)
        if clics:
            out["cpc"] = round(dep / clics, 2)
        return out
    meta = {"impressions": entier(s("FAEV01")), "reach": entier(d("FAEV03")), "spend": arrondi(s("FAEV04")),
            "clicks": entier(s("FAEV05"))}
    tiktok = {"impressions": entier(s("KAEV01")), "spend": arrondi(s("KAEV02")), "clicks": entier(s("KAEV03")),
              "conversions": entier(s("KAEV04"))}
    meta.update(couts(meta["impressions"] or 0, meta["clicks"] or 0, meta["spend"] or 0))
    tiktok.update(couts(tiktok["impressions"] or 0, tiktok["clicks"] or 0, tiktok["spend"] or 0))
    if meta.get("impressions") and meta.get("reach"):
        meta["frequency"] = round(meta["impressions"] / meta["reach"], 2)
    if meta.get("impressions") and ((meta.get("reach") or 0) > meta["impressions"] or (meta.get("ctr") or 0) > 10):
        print("ATTENTION : chiffres Meta Ads incohérents dans Metricool (portée supérieure aux impressions ou CTR anormal), "
              "synchronisation probablement partielle. Recouper avec le Gestionnaire de publicités avant de publier.",
              file=sys.stderr)
    garder = lambda x: {a: b for a, b in x.items() if b is not None}  # noqa: E731
    meta, tiktok = garder(meta), garder(tiktok)
    return (meta if meta.get("impressions") else None, tiktok if tiktok.get("impressions") else None)


def table_posts(lignes, champs, tri, colonnes, limite=5, transformer=None):
    rows = []
    for l in lignes or []:
        r = dict(zip(champs, l))
        r = {k: (num(v) if k not in ("date", "texte", "url", "type", "name", "objective", "resultLabel") else v) for k, v in r.items()}
        if transformer:
            r = transformer(r)
        if r is not None:
            rows.append(r)
    rows.sort(key=lambda r: (r.get(tri) or 0), reverse=True)
    return {"columns": colonnes, "rows": rows[:limite]}


PAYS = {
    "FR": "France", "DZ": "Algérie", "MA": "Maroc", "TN": "Tunisie", "BE": "Belgique", "CH": "Suisse",
    "LU": "Luxembourg", "ES": "Espagne", "PT": "Portugal", "IT": "Italie", "DE": "Allemagne", "NL": "Pays-Bas",
    "GB": "Royaume-Uni", "IE": "Irlande", "GR": "Grèce", "PL": "Pologne", "RO": "Roumanie", "HU": "Hongrie",
    "LT": "Lituanie", "SE": "Suède", "DK": "Danemark", "NO": "Norvège", "FI": "Finlande", "AT": "Autriche",
    "CZ": "Tchéquie", "SK": "Slovaquie", "BG": "Bulgarie", "HR": "Croatie", "RS": "Serbie", "UA": "Ukraine",
    "RU": "Russie", "TR": "Turquie", "US": "États-Unis", "CA": "Canada", "MX": "Mexique", "BR": "Brésil",
    "AR": "Argentine", "CO": "Colombie", "PE": "Pérou", "CL": "Chili", "HT": "Haïti", "CI": "Côte d'Ivoire",
    "SN": "Sénégal", "CM": "Cameroun", "BJ": "Bénin", "TG": "Togo", "ML": "Mali", "BF": "Burkina Faso",
    "NE": "Niger", "GN": "Guinée", "GA": "Gabon", "CG": "Congo-Brazzaville", "CD": "RD Congo", "TD": "Tchad",
    "MG": "Madagascar", "MU": "Maurice", "KM": "Comores", "DJ": "Djibouti", "NG": "Nigeria", "GH": "Ghana",
    "KE": "Kenya", "TZ": "Tanzanie", "UG": "Ouganda", "ET": "Éthiopie", "ZA": "Afrique du Sud", "EG": "Égypte",
    "LY": "Libye", "MR": "Mauritanie", "LB": "Liban", "SA": "Arabie saoudite", "AE": "Émirats arabes unis",
    "QA": "Qatar", "BH": "Bahreïn", "KW": "Koweït", "IL": "Israël", "IR": "Iran", "IQ": "Irak", "IN": "Inde",
    "PK": "Pakistan", "BD": "Bangladesh", "LK": "Sri Lanka", "CN": "Chine", "HK": "Hong Kong", "TW": "Taïwan",
    "JP": "Japon", "KR": "Corée du Sud", "VN": "Viêt Nam", "TH": "Thaïlande", "ID": "Indonésie",
    "PH": "Philippines", "MY": "Malaisie", "SG": "Singapour", "AU": "Australie", "NZ": "Nouvelle-Zélande",
    "KZ": "Kazakhstan", "RE": "La Réunion", "YT": "Mayotte", "GP": "Guadeloupe", "MQ": "Martinique",
    "GF": "Guyane", "NC": "Nouvelle-Calédonie", "PF": "Polynésie française", "WF": "Wallis-et-Futuna",
    "PM": "Saint-Pierre-et-Miquelon", "MC": "Monaco", "AD": "Andorre",
}
def pourcentages(lignes, renommer=None, exclure=("Autres",)):
    """Lignes [libellé, part entre 0 et 1] -> [(libellé, %)] triées, libellés renommés et regroupés."""
    total, ordre = {}, []
    for l in lignes or []:
        if len(l) < 2:
            continue
        nom = str(l[0] or "").strip().replace("’", "'")
        v = num(l[1])
        if v is None or not nom or nom in exclure:
            continue
        nom = renommer(nom) if renommer else nom
        if nom not in total:
            ordre.append(nom)
            total[nom] = 0.0
        total[nom] += v
    items = [(n, round(total[n] * 100, 2)) for n in ordre]
    items.sort(key=lambda x: -x[1])
    return items


def top_lignes(items, lignes_max=6, noms_max=4, autres="autres"):
    """Regroupe les ex aequo sur une ligne (« Portugal · Italie · Espagne ») comme dans les rapports."""
    rows, i = [], 0
    while i < len(items) and len(rows) < lignes_max:
        j = i
        while j + 1 < len(items) and items[j + 1][1] == items[i][1]:
            j += 1
        noms = [n for n, _ in items[i:j + 1]]
        if len(noms) > noms_max and len(rows) >= 5:
            break  # longue traîne d'ex aequo : on s'arrête là plutôt que d'afficher une ligne fourre-tout
        lib = " · ".join(noms) if len(noms) <= noms_max else "%s et %d %s" % (" · ".join(noms[:3]), len(noms) - 3, autres)
        rows.append([lib, items[i][1]])
        i = j + 1
    return rows


def nom_pays(code):
    return PAYS.get(code.upper(), code) if len(code) == 2 else code


def nom_lieu(texte):
    return texte.split(",")[0].strip()


def audience_reseau(dossier: Path, conf, reseau):
    """Bloc « Démographie : pays et villes » (Facebook, Instagram) à partir des répartitions Metricool."""
    groupes = []
    pays = charger(dossier, "audience_%s_pays" % reseau, conf.get("audience_%s_pays" % reseau, {}).get("metrics", []))
    if pays:
        groupes.append({"title": "Top des pays", "items": top_lignes(pourcentages(pays, nom_pays), 7, 4, "autres pays")})
    villes = charger(dossier, "audience_%s_villes" % reseau, conf.get("audience_%s_villes" % reseau, {}).get("metrics", []))
    if villes:
        groupes.append({"title": "Top des villes", "items": top_lignes(pourcentages(villes, nom_lieu), 7, 4, "autres villes")})
    groupes = [g for g in groupes if g["items"]]
    return [{"title": "Démographie : pays et villes", "groups": groupes}] if groupes else None


def concurrents(lignes, champs, colonnes, soi, ordre_prefere):
    """Tableau des concurrents : ForgeMe en tête puis les comptes suivis dans Metricool."""
    rows = []
    for l in lignes or []:
        r = dict(zip(champs, l))
        nom = str(r.get("display") or r.get("name") or r.get("screen") or "").split("|")[0].strip()
        if not nom:
            continue
        row = {"name": nom}
        for c in colonnes:
            v = num(r.get(c))
            row[c] = None if v is None else (entier(v) if c in ("followers", "posts", "reels") else round(v, 2))
        rows.append(row)
    if not rows:
        return None
    rang = {n: i for i, n in enumerate(ordre_prefere)}
    rows.sort(key=lambda r: (rang.get(r["name"], len(rang)), -(r.get("followers") or 0)))
    moi = {"name": "ForgeMe", "self": True}
    moi.update({c: soi.get(c) for c in colonnes})
    return {"columns": colonnes, "rows": [moi] + rows, "note": A_REDIGER}


def hashtags(lignes, limite=5):
    rows = []
    for l in lignes or []:
        if len(l) < 4 or not l[0]:
            continue
        rows.append({"tag": str(l[0]).strip(), "posts": entier(num(l[1])), "views": entier(num(l[2])),
                     "likes": entier(num(l[3]))})
    rows.sort(key=lambda r: (-(r["views"] or 0), -(r["posts"] or 0), r["tag"]))
    return {"rows": rows[:limite]} if rows else None


def blocs_complementaires(dossier: Path, mois_obj):
    """Ajoute audience, concurrents et hashtags au mois (Facebook, Instagram) quand les fichiers existent."""
    conf_all = config()["metricool"]
    conf = conf_all["requetes"]
    ordre = conf_all.get("concurrents", {})

    def kv(res, k):
        v = ((mois_obj.get(res) or {}).get("kpi") or {}).get(k)
        return v.get("v") if isinstance(v, dict) else v
    if "facebook" in mois_obj:
        aud = audience_reseau(dossier, conf, "facebook")
        if aud:
            mois_obj["facebook"]["audience"] = aud
        lignes = charger(dossier, "concurrents_facebook", conf.get("concurrents_facebook", {}).get("metrics", []))
        if lignes:
            soi = {k: kv("facebook", k) for k in ("followers", "posts", "reactions", "engagement")}
            t = concurrents(lignes, ["name", "followers", "posts", "reactions", "engagement"],
                            ["followers", "posts", "reactions", "engagement"], soi, ordre.get("facebook", []))
            if t:
                mois_obj["facebook"]["competitors"] = t
    if "instagram" in mois_obj:
        aud = audience_reseau(dossier, conf, "instagram")
        if aud:
            mois_obj["instagram"]["audience"] = aud
        lignes = charger(dossier, "hashtags_instagram", conf.get("hashtags_instagram", {}).get("metrics", []))
        t = hashtags(lignes)
        if t:
            mois_obj["instagram"]["hashtags"] = t
        lignes = charger(dossier, "concurrents_instagram", conf.get("concurrents_instagram", {}).get("metrics", []))
        if lignes:
            soi = {k: kv("instagram", k) for k in ("followers", "posts", "reels", "engagement")}
            t = concurrents(lignes, ["screen", "display", "followers", "posts", "reels", "engagement"],
                            ["followers", "posts", "reels", "engagement"], soi, ordre.get("instagram", []))
            if t:
                mois_obj["instagram"]["competitors"] = t
    return mois_obj


def preparer(mois, dossier: Path, jusqua=None):
    conf = config()["metricool"]["requetes"]
    sortie = {"id": mois, "status": "draft", "autoPills": True,
              "overview": {"facebook": {"note": A_REDIGER}, "instagram": {"note": A_REDIGER},
                           "ads": {"note": A_REDIGER}}}
    if jusqua:
        sortie["until"] = jusqua

    fb = charger(dossier, "facebook", conf["facebook"]["metrics"])
    if fb:
        sortie["facebook"] = {"kpi": kpis_facebook(fb, conf["facebook"]["metrics"]), "analysis": A_REDIGER}
        jour = serie_jour(fb, conf["facebook"]["metrics"], "FBEV17")
        if jour:
            sortie["facebook"]["daily"] = jour
        posts = charger(dossier, "posts_facebook", conf["posts_facebook"]["metrics"])
        champs_posts = ["date", "texte", "url", "type", "reach", "reactions", "comments", "shares", "clicks", "engagement",
                        "impressions"]
        reels_sans_texte = []
        if posts and config()["metricool"].get("facebook_videos_sans_texte_en_reels"):
            # Vérifié dans Meta Business Suite le 25 novembre 2026 : les « posts » vidéo sans légende que
            # Metricool remonte pour la page ForgeMe sont en réalité des reels.
            garder = []
            for l in posts:
                r = dict(zip(champs_posts, l))
                if str(r.get("type") or "").lower() == "video" and not str(r.get("texte") or "").strip():
                    reels_sans_texte.append(r)
                else:
                    garder.append(l)
            posts = garder
            if reels_sans_texte:
                k = sortie["facebook"]["kpi"]
                k["reels"] = (k.get("reels") or 0) + len(reels_sans_texte)
                k["posts"] = max((k.get("posts") or 0) - len(reels_sans_texte), 0)
        if sortie["facebook"]["kpi"].get("posts") == 0:
            # sans post du fil, l'engagement et la portée moyenne « par post » n'ont pas de sens
            for cle in ("engagement", "avgReachPerPost"):
                sortie["facebook"]["kpi"].pop(cle, None)
        if posts:
            def tf(r):
                return {"date": date_iso(r["date"]), "title": titre_par_defaut(r["texte"]) or A_REDIGER, "texte": r["texte"],
                        "url": r["url"], "reach": entier(r["reach"]), "reactions": entier(r["reactions"]),
                        "comments": entier(r["comments"]), "shares": entier(r["shares"]),
                        "clicks": entier(r["clicks"]), "engagement": arrondi(r["engagement"])}
            t = table_posts(posts, champs_posts, "engagement",
                            ["reach", "reactions", "comments", "shares", "clicks", "engagement"], 5, tf)
            if t["rows"]:
                sortie["facebook"]["posts"] = t
        reels = charger(dossier, "reels_facebook", conf["reels_facebook"]["metrics"]) or []
        if reels or reels_sans_texte:
            def trf(r):
                return {"date": date_iso(r["date"]), "title": titre_par_defaut(r["texte"]), "texte": r["texte"],
                        "url": r["url"], "views": entier(r["views"]), "likes": entier(r["likes"])}
            t = table_posts(reels, ["date", "texte", "url", "views", "reach", "likes", "actions", "engagement", "tempsMoyen"],
                            "views", ["views", "likes"], 8, trf)
            for r in reels_sans_texte:
                d = date_iso(r["date"])
                t["rows"].append({"date": d, "title": "Reel du %s, sans légende" % jour_mois(d), "url": r["url"],
                                  "views": entier(num(r.get("impressions"))), "likes": entier(num(r.get("reactions")))})
            t["rows"].sort(key=lambda x: (-(x.get("views") or 0), x["date"]))
            if t["rows"]:
                sortie["facebook"]["reels"] = t

    ig = charger(dossier, "instagram", conf["instagram"]["metrics"])
    if ig:
        plus = charger(dossier, "instagram_plus", conf["instagram_plus"]["metrics"])
        sortie["instagram"] = {"kpi": kpis_instagram(ig, conf["instagram"]["metrics"], plus, conf["instagram_plus"]["metrics"]),
                               "analysis": A_REDIGER}
        jour = serie_jour(ig, conf["instagram"]["metrics"], "IGEV01")
        if jour:
            sortie["instagram"]["daily"] = jour
        posts = charger(dossier, "posts_instagram", conf["posts_instagram"]["metrics"])
        if posts:
            def ti(r):
                return {"date": date_iso(r["date"]), "title": titre_par_defaut(r["texte"]), "texte": r["texte"],
                        "url": r["url"], "format": FORMATS_IG.get(r["type"], r["type"]),
                        "views": entier(r["views"]), "reach": entier(r["reach"]), "likes": entier(r["likes"]),
                        "engagement": arrondi(r["engagement"])}
            t = table_posts(
                posts, ["date", "texte", "url", "type", "views", "reach", "engagement", "interactions", "likes", "comments", "shares", "saves"],
                "engagement", ["format", "views", "reach", "likes", "engagement"], 5, ti)
            if t["rows"]:
                sortie["instagram"]["posts"] = t
        reels = charger(dossier, "reels_instagram", conf["reels_instagram"]["metrics"])
        if reels:
            def tr(r):
                return {"date": date_iso(r["date"]), "title": titre_par_defaut(r["texte"]), "texte": r["texte"],
                        "url": r["url"], "views": entier(r["views"]), "reach": entier(r["reach"]),
                        "likes": entier(r["likes"]), "engagement": arrondi(r["engagement"])}
            t = table_posts(reels, ["date", "texte", "url", "views", "reach", "engagement", "interactions", "likes"],
                            "views", ["views", "reach", "likes", "engagement"], 6, tr)
            if t["rows"]:
                sortie["instagram"]["reels"] = t
        stories = charger(dossier, "stories_instagram", conf["stories_instagram"]["metrics"])
        if stories:
            def ts(r):
                return {"date": date_iso(r["date"]), "title": titre_par_defaut(r["texte"]) or "Story", "url": r["url"],
                        "impressions": entier(r["impressions"]), "reach": entier(r["reach"])}
            t = table_posts(stories, ["date", "texte", "url", "type", "impressions", "reach", "replies", "tapsForward", "exits"],
                            "reach", ["reach", "impressions"], 8, ts)
            if t["rows"]:
                sortie["instagram"]["stories"] = t

    pub = charger(dossier, "publicite", conf["publicite"]["metrics"])
    if pub:
        meta, tiktok = kpis_publicite(pub, conf["publicite"]["metrics"])
        if meta or tiktok:
            sortie["ads"] = {"analysis": A_REDIGER}
            if meta:
                sortie["ads"]["meta"] = {"kpi": meta}
            if tiktok:
                sortie["ads"]["tiktok"] = {"kpi": tiktok}
        cm = charger(dossier, "campagnes_meta", conf["campagnes_meta"]["metrics"])
        if cm and meta:
            def tm(r):
                if not r.get("impressions"):
                    return None
                impr, clics, dep = r["impressions"], r.get("clicks") or 0, r.get("spend") or 0
                res = r.get("results")
                return {"name": nom_campagne(r["name"]), "impressions": entier(impr), "reach": entier(r.get("reach")),
                        "frequency": round(impr / r["reach"], 2) if r.get("reach") else None, "results": entier(res),
                        "costPerResult": round(dep / res, 2) if res else None, "installs": entier(r.get("installs")),
                        "clicks": entier(clics), "cpm": round(dep / impr * 1000, 2), "spend": arrondi(dep)}
            t = table_posts(cm, ["name", "objective", "impressions", "reach", "spend", "clicks", "linkClicks", "installs",
                                 "results", "resultLabel", "thruPlays"], "impressions",
                            ["impressions", "reach", "frequency", "results", "costPerResult", "installs", "clicks", "cpm", "spend"], 6, tm)
            if t["rows"]:
                sortie["ads"]["meta"]["campaigns"] = t
            totaux_campagnes(sortie["ads"]["meta"]["kpi"], cm,
                             ["name", "objective", "impressions", "reach", "spend", "clicks", "linkClicks", "installs",
                              "results", "resultLabel", "thruPlays"],
                             ("linkClicks", "installs", "results", "thruPlays"))
            km = sortie["ads"]["meta"]["kpi"]
            somme = sum(r.get("spend") or 0 for r in t["rows"])
            if km.get("spend") and abs(somme - km["spend"]) > max(0.5, km["spend"] * 0.01):
                print("ATTENTION : dépense Meta du compte (%.2f €) différente de la somme des campagnes (%.2f €), "
                      "synchronisation Metricool décalée entre les deux niveaux." % (km["spend"], somme), file=sys.stderr)
            if (km.get("linkClicks") or 0) > (km.get("clicks") or 0):
                print("ATTENTION : plus de clics sur le lien que de clics dans Metricool, clics Meta à vérifier.", file=sys.stderr)
            simplifier_resultats(sortie["ads"]["meta"], objectif_app(cm, 1))
        ct = charger(dossier, "campagnes_tiktok", conf["campagnes_tiktok"]["metrics"])
        if ct and tiktok:
            def tt(r):
                if not r.get("impressions"):
                    return None
                impr, clics, dep = r["impressions"], r.get("clicks") or 0, r.get("spend") or 0
                res = r.get("results")
                return {"name": nom_campagne(r["name"]), "impressions": entier(impr), "clicks": entier(clics),
                        "results": entier(res), "costPerResult": round(dep / res, 2) if res else None,
                        "cpc": round(dep / clics, 2) if clics else None, "ctr": round(clics / impr * 100, 2),
                        "spend": arrondi(dep)}
            t = table_posts(ct, ["name", "objective", "impressions", "clicks", "conversions", "spend", "results", "frequency",
                                 "videoViews", "views6s", "profileVisits", "follows"], "impressions",
                            ["impressions", "clicks", "results", "costPerResult", "cpc", "ctr", "spend"], 6, tt)
            if t["rows"]:
                sortie["ads"]["tiktok"]["campaigns"] = t
            totaux_campagnes(sortie["ads"]["tiktok"]["kpi"], ct,
                             ["name", "objective", "impressions", "clicks", "conversions", "spend", "results", "frequency",
                              "videoViews", "views6s", "profileVisits", "follows"],
                             ("results", "videoViews", "views6s", "profileVisits", "follows"))
            simplifier_resultats(sortie["ads"]["tiktok"], objectif_app(ct, 1))

    blocs_complementaires(dossier, sortie)
    sortie["takeaways"] = {"wins": [A_REDIGER], "priorities": [A_REDIGER]}
    return sortie


def totaux_campagnes(kpi, lignes, champs, cles):
    """Additionne sur toutes les campagnes les indicateurs absents de l'évolution (installations, résultats, vidéo)."""
    somme = {}
    for l in lignes or []:
        r = dict(zip(champs, l))
        for c in cles:
            v = num(r.get(c))
            if v is not None:
                somme[c] = somme.get(c, 0) + v
    for c, v in somme.items():
        if v:
            kpi[c] = entier(v)
    dep = kpi.get("spend") or 0
    if kpi.get("installs"):
        kpi["costPerInstall"] = round(dep / kpi["installs"], 2)
    if kpi.get("results"):
        kpi["costPerResult"] = round(dep / kpi["results"], 2)


def objectif_app(lignes, col):
    """Vrai si toutes les campagnes ont un objectif d'installation d'application."""
    objs = [str(l[col] or "").upper() for l in lignes or [] if len(l) > col]
    return bool(objs) and all("APP" in o for o in objs)


def simplifier_resultats(plat, app):
    """Pour des campagnes d'installation, les « résultats » sont les installations : on n'affiche qu'une fois."""
    k = plat.get("kpi") or {}
    if app and k.get("results") is not None and k.get("installs") is None:
        k["installs"] = k["results"]
        if k.get("costPerResult") is not None:
            k["costPerInstall"] = k["costPerResult"]
    if k.get("installs") is not None and k.get("conversions") == k.get("installs"):
        k.pop("conversions", None)
    if k.get("installs") is not None and k.get("results") in (None, k.get("installs")):
        k.pop("results", None)
        k.pop("costPerResult", None)
        camp = plat.get("campaigns")
        if camp:
            for r in camp["rows"]:
                if r.get("installs") is None:
                    r["installs"] = r.get("results")
                r.pop("results", None)
                r.pop("costPerResult", None)
                if r.get("installs") and r.get("spend") is not None:
                    r["costPerInstall"] = round(r["spend"] / r["installs"], 2)
            cols = [c for c in camp["columns"] if c not in ("results", "costPerResult", "installs", "costPerInstall")]
            camp["columns"] = cols[:-1] + ["installs", "costPerInstall"] + cols[-1:]


def fusion_table(ancienne, nouvelle):
    """Nouvelle table de publications en gardant les titres déjà rédigés (même lien, sinon même date)."""
    if not ancienne or not ancienne.get("rows"):
        return nouvelle
    par_url = {r.get("url"): r for r in ancienne["rows"] if r.get("url")}
    par_date = {}
    for r in ancienne["rows"]:
        par_date.setdefault(r.get("date"), []).append(r)
    for r in nouvelle.get("rows", []):
        vieux = par_url.get(r.get("url"))
        if vieux is None and len(par_date.get(r.get("date"), [])) == 1 and not par_date[r.get("date")][0].get("url"):
            vieux = par_date[r.get("date")][0]
        if vieux and vieux.get("title"):
            r["title"] = vieux["title"]
            if not r.get("url") and vieux.get("url"):
                r["url"] = vieux["url"]
        elif r.get("url") or r.get("date"):
            r["nouveau"] = True
    return nouvelle


def actualiser(mois, dossier: Path, jusqua=None):
    """Remet à jour les chiffres d'un mois déjà rédigé sans toucher aux textes ni aux titres déjà écrits.

    Renvoie le mois actualisé et la liste des changements à reprendre dans les textes."""
    import copy
    from commun import lire_donnees
    donnees = lire_donnees()
    ancien = next((m for m in donnees["months"] if m["id"] == mois), None)
    if ancien is None:
        sys.exit("Le mois %s n'existe pas encore : utilise preparer." % mois)
    neuf = preparer(mois, dossier, jusqua)
    out = copy.deepcopy(ancien)
    an, m = (int(x) for x in mois.split("-"))
    if jusqua and int(jusqua.split("-")[2]) < calendar.monthrange(an, m)[1]:
        out["until"] = jusqua
    else:
        out.pop("until", None)
        out.pop("untilNote", None)
    for res in ("facebook", "instagram"):
        if res not in neuf:
            continue
        o = out.setdefault(res, {"analysis": A_REDIGER})
        o["kpi"] = neuf[res]["kpi"]
        if "daily" in neuf[res]:
            o["daily"] = neuf[res]["daily"]
        for cle in ("posts", "reels", "stories"):
            if cle in neuf[res]:
                o[cle] = fusion_table(o.get(cle), neuf[res][cle])
            else:
                o.pop(cle, None)
        for cle in ("audience", "hashtags"):
            if cle in neuf[res]:
                o[cle] = neuf[res][cle]
        if "competitors" in neuf[res]:
            note = (o.get("competitors") or {}).get("note")
            o["competitors"] = neuf[res]["competitors"]
            if note:
                o["competitors"]["note"] = note
    if "ads" in neuf:
        a = out.setdefault("ads", {"analysis": A_REDIGER})
        for plat in ("meta", "tiktok"):
            if plat not in neuf["ads"]:
                continue
            p = a.setdefault(plat, {})
            p["kpi"] = neuf["ads"][plat]["kpi"]
            if "campaigns" in neuf["ads"][plat]:
                p["campaigns"] = neuf["ads"][plat]["campaigns"]
            if p.get("title") == "Lancement des campagnes":
                p.pop("title")
    changements = []

    def val(x):
        return x.get("v") if isinstance(x, dict) else x
    for res in ("facebook", "instagram"):
        avant, apres = (ancien.get(res) or {}).get("kpi") or {}, (out.get(res) or {}).get("kpi") or {}
        for k in sorted(set(avant) | set(apres)):
            if val(avant.get(k)) != val(apres.get(k)):
                changements.append("%s.%s : %s -> %s" % (res, k, val(avant.get(k)), val(apres.get(k))))
        for cle in ("posts", "reels", "stories"):
            for r in ((out.get(res) or {}).get(cle) or {}).get("rows", []):
                if r.pop("nouveau", False):
                    changements.append("%s.%s : nouvelle publication du %s à titrer (%s)" % (res, cle, r.get("date"), r.get("url") or "sans lien"))
    for res in ("facebook", "instagram"):
        for cle in ("posts", "reels", "stories"):
            vieux = {(r.get("url") or r.get("date")): r for r in (((ancien.get(res) or {}).get(cle) or {}).get("rows") or [])}
            for r in (((out.get(res) or {}).get(cle) or {}).get("rows") or []):
                v = vieux.get(r.get("url") or r.get("date"))
                if not v:
                    continue
                for k, x in r.items():
                    if isinstance(x, (int, float)) and v.get(k) != x:
                        changements.append("%s.%s « %s » : %s %s -> %s" % (res, cle, r.get("title"), k, v.get(k), x))
    for plat in ("meta", "tiktok"):
        avant = ((ancien.get("ads") or {}).get(plat) or {}).get("kpi") or {}
        apres = ((out.get("ads") or {}).get(plat) or {}).get("kpi") or {}
        for k in sorted(set(avant) | set(apres)):
            if val(avant.get(k)) != val(apres.get(k)):
                changements.append("ads.%s.%s : %s -> %s" % (plat, k, val(avant.get(k)), val(apres.get(k))))
    return out, changements


def comparer(mois_obj):
    """Affiche les chiffres du mois face au mois précédent (si le mot de passe est disponible)."""
    import os
    if not os.environ.get("FM_MOT_DE_PASSE"):
        return
    from commun import lire_donnees
    donnees = lire_donnees()
    precedents = [m for m in donnees["months"] if m["id"] < mois_obj["id"]]
    if not precedents:
        return
    prec = precedents[-1]
    print("\nComparaison avec %s :" % prec["id"])

    def val(x):
        return x.get("v") if isinstance(x, dict) else x
    for res in ("facebook", "instagram"):
        for k, v in (mois_obj.get(res, {}).get("kpi") or {}).items():
            pv = val((prec.get(res, {}).get("kpi") or {}).get(k))
            print("  %-10s %-18s %10s   (avant : %s)" % (res, k, v, pv))
    for sous in ("meta", "tiktok"):
        for k, v in (mois_obj.get("ads", {}).get(sous, {}).get("kpi") or {}).items():
            pv = val(((prec.get("ads") or {}).get(sous, {}).get("kpi") or {}).get(k))
            print("  %-10s %-18s %10s   (avant : %s)" % (sous, k, v, pv))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("requetes")
    r.add_argument("mois")
    r.add_argument("--jusqu-au", dest="jusqua")
    p = sp.add_parser("preparer")
    p.add_argument("mois")
    p.add_argument("--brut", required=True)
    p.add_argument("--sortie", required=True)
    p.add_argument("--jusqu-au", dest="jusqua")
    u = sp.add_parser("actualiser")
    u.add_argument("mois")
    u.add_argument("--brut", required=True)
    u.add_argument("--sortie", required=True)
    u.add_argument("--jusqu-au", dest="jusqua")
    a = ap.parse_args()
    conf = config()["metricool"]
    if a.cmd == "requetes":
        debut, fin = periode(a.mois, conf["fuseau"], a.jusqua)
        print(json.dumps({"brandId": conf["brandId"], "from": debut, "to": fin,
                          "fichiers": {nom: q["metrics"] for nom, q in conf["requetes"].items()}},
                         ensure_ascii=False, indent=1))
        return 0
    if a.jusqua:
        periode(a.mois, conf["fuseau"], a.jusqua)
    if a.cmd == "actualiser":
        mois, changements = actualiser(a.mois, Path(a.brut), a.jusqua)
        Path(a.sortie).write_text(json.dumps(mois, ensure_ascii=False, indent=1), encoding="utf-8")
        print("Mois %s actualisé dans %s" % (a.mois, a.sortie))
        print("\n".join(["Changements à reprendre dans les textes :"] + ["  " + c for c in changements])
              if changements else "Aucun chiffre n'a changé.")
        return 0
    mois = preparer(a.mois, Path(a.brut), a.jusqua)
    Path(a.sortie).write_text(json.dumps(mois, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Mois %s préparé dans %s" % (a.mois, a.sortie))
    comparer(mois)
    return 0


if __name__ == "__main__":
    sys.exit(main())
