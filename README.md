# Statistiques réseaux sociaux · ForgeMe

Espace de suivi mensuel des performances Facebook, Instagram, Meta Ads et TikTok Ads de l'application ForgeMe, préparé par Sarah Beets, community manager.

La page est protégée par un mot de passe : les chiffres sont chiffrés (AES-256) et ne s'affichent qu'une fois le mot de passe saisi. Le mot de passe n'est jamais enregistré dans ce dépôt.

## Organisation

| Élément | Rôle |
|---|---|
| `index.html` | la page vue par le client (mois validés uniquement) |
| `apercu/index.html` | la version d'aperçu, avec les mois en attente de validation |
| `data/donnees.enc` | toutes les données, chiffrées |
| `src/` | modèle de la page, polices (Inter, Gochi Hand) et mascottes de la charte ForgeMe |
| `scripts/` | outils de mise à jour |

## Mise à jour mensuelle

Toutes les commandes demandent le mot de passe dans la variable `FM_MOT_DE_PASSE`.

1. `python3 scripts/metricool.py requetes AAAA-MM` donne la période et les métriques à exporter pour la marque FORGE ME (ajouter `--jusqu-au AAAA-MM-JJ` pour un mois en cours).
2. Les réponses brutes sont enregistrées dans un dossier de travail (hors du dépôt), un fichier par requête, y compris `instagram_plus`, les reels Facebook et Instagram, les stories, la publicité (`publicite`, `campagnes_meta`, `campagnes_tiktok`), les répartitions d'audience (`audience_*`), les concurrents (`concurrents_*`) et les hashtags (`hashtags_instagram`).
3. `python3 scripts/metricool.py preparer AAAA-MM --brut DOSSIER --sortie mois.json` calcule les indicateurs, les courbes d'abonnés jour par jour et les classements.
4. Les chiffres publicitaires détaillés relevés dans le Gestionnaire de publicités Meta et dans TikTok Ads Manager (résultats, installations, répétition, vues vidéo, tableaux des campagnes et des publicités) sont ajoutés dans `mois.json`, puis les textes (analyses, recommandations, titres des publications, bilan) y sont rédigés et `python3 scripts/donnees.py verifier mois.json` contrôle le tout.
5. `python3 scripts/donnees.py ajouter-mois mois.json` puis `python3 scripts/build.py` : le mois apparaît dans l'aperçu.
6. Après validation : `python3 scripts/donnees.py publier AAAA-MM` puis `python3 scripts/build.py`.

Pour un nouveau dépôt, `python3 scripts/donnees.py initialiser base.json` crée les données chiffrées à partir d'un fichier contenant l'auteur et l'historique des abonnés.

Dépendance Python : `cryptography`.

## Changer le mot de passe

1. `FM_MOT_DE_PASSE=ancien FM_NOUVEAU_MOT_DE_PASSE=nouveau python3 scripts/donnees.py changer-mot-de-passe`
2. `FM_MOT_DE_PASSE=nouveau python3 scripts/build.py`

Les personnes restées connectées devront saisir le nouveau mot de passe à leur prochaine visite.

## Polices et visuels

Inter et Gochi Hand sont distribuées sous licence SIL Open Font License (voir `src/fonts`). Les mascottes et l'icône appartiennent à ForgeMe.
