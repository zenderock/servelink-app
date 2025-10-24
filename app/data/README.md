# Project Presets

Ce dossier contient les configurations des templates/boilerplates de projets affichés dans la page de création de nouveau projet.

## Structure du fichier `project_presets.json`

```json
{
  "presets": [
    {
      "id": "identifiant-unique",
      "title": "Titre du template",
      "description": "Description détaillée du template",
      "github_url": "https://github.com/votre-org/votre-repo",
      "doc_url": "https://docs.servelink.io/templates/votre-template",
      "tags": ["Tag1", "Tag2", "Tag3"],
      "icon": "nom-icone"
    }
  ]
}
```

## Champs

- **id**: Identifiant unique du preset (kebab-case)
- **title**: Titre affiché sur la carte
- **description**: Description courte et claire du template
- **github_url**: URL du repository GitHub à cloner
- **doc_url**: URL de la documentation (optionnel)
- **tags**: Liste des technologies/frameworks utilisés (max 4-5 recommandé)
- **icon**: Nom de l'icône (pour usage futur)

## Ajouter un nouveau preset

1. Ouvrez le fichier `project_presets.json`
2. Ajoutez un nouvel objet dans le tableau `presets`
3. Remplissez tous les champs requis
4. Sauvegardez le fichier

Les changements seront pris en compte au prochain rechargement de la page.

## Bonnes pratiques

- Gardez les descriptions concises (max 2 lignes)
- Utilisez 3-5 tags maximum pour la lisibilité
- Assurez-vous que les URLs GitHub sont valides et publiques
- Testez les liens de documentation avant de les ajouter
