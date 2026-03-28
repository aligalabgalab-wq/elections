🗳️ Plateforme de Vote Électronique Sécurisée

📌 Description
Ce projet est une plateforme de vote électronique sécurisée développée dans un cadre académique à l’Université de Djibouti.
L’objectif est de concevoir un système capable de reproduire un processus électoral fiable, contrôlé et cohérent. Contrairement à une simple application web, cette plateforme repose sur une logique métier stricte où chaque règle démocratique est traduite en contrainte technique.
Le système ne se limite pas à permettre le vote. Il encadre, vérifie et trace chaque action afin de garantir l’intégrité du processus électoral.

🎯 Objectifs
•	Garantir l’authentification des utilisateurs 
•	Empêcher le double vote 
•	Respecter le cadre temporel de l’élection 
•	Assurer la traçabilité des opérations 
•	Préserver la confidentialité du vote 
•	Traduire les règles électorales en logique informatique fiable 

👥 Équipe
•	Galab Ali Galab
•	Choueb Karrieh Dini
•	Hassan Moussa Ahmed
•	Balkis Youssouf Osman
 Encadré par : Dr. Moubarak

⚙️ Technologies utilisées
•	Python (Flask) 
•	SQLAlchemy 
•	MySQL 
•	Flask-Login 
•	HTML 
•	CSS 
•	JavaScript 
•	Jinja (templates) 

🚀 Fonctionnalités
👤 Côté électeur
•	S’inscrire et s’authentifier 
•	Consulter les candidats 
•	Voter (une seule fois) 
•	Accéder uniquement pendant la période de vote 
💼 Côté candidat
•	Soumettre une candidature 
•	Fournir les informations requises 
•	Attendre validation administrative 
🔐 Côté administrateur
•	Gérer les candidats (validation/rejet) 
•	Contrôler le cycle électoral 
•	Superviser les votes 
•	Consulter les résultats 
👁️ Côté visiteur
•	Consulter les informations publiques 
•	Voir les candidats 

🗂️ Structure du projet
•	main.py → logique métier et routes 
•	config.py → configuration globale 
•	/models → structure des données (SQLAlchemy) 
•	/templates → interface utilisateur (Jinja) 
•	/static → fichiers CSS, JS, images 

🏗️ Architecture
Le système repose sur une architecture en trois couches :
•	Présentation : interface utilisateur (HTML, CSS, JS) 
•	Logique métier : contrôle des règles et validation des actions 
•	Données : base MySQL avec contraintes strictes 
Chaque couche vérifie la cohérence des opérations, assurant une chaîne de contrôle complète.

🔐 Sécurité
•	Authentification sécurisée (mots de passe hachés) 
•	Gestion des sessions avec Flask-Login 
•	Protection CSRF 
•	Séparation stricte des rôles 
•	Prévention du double vote (logique + base de données) 
•	Journalisation des actions (traçabilité) 
•	Séparation identité / vote pour garantir l’anonymat 

🔄 Cycle électoral
Le système suit une logique par phases :
1.	Préparation 
2.	Ouverture du vote 
3.	Fermeture du vote 
4.	Dépouillement 
5.	Publication des résultats 
Chaque étape est contrôlée et aucune transition n’est libre.

Tests
Les tests réalisés :
•	Tests unitaires (modèles, contraintes) 
•	Tests d’intégration (simulation complète d’élection) 
•	Tests de sécurité (double vote, accès interdit) 
•	Tests d’interface 
Résultat : ✔️ Système cohérent, contrôlé et fonctionnel

⚠️ Limites
•	Pas de chiffrement avancé des votes 
•	Pas de protocole cryptographique complet 
•	Hébergement local uniquement 
•	Non adapté à une élection réelle à grande échelle 

🔮 Améliorations futures
•	Authentification forte (2FA) 
•	Intégration de mécanismes cryptographiques 
•	Déploiement sécurisé en ligne 
•	Audit externe du système 
•	Amélioration de l’interface utilisateur 

📄 Licence
Projet académique – Université de Djibouti

🙏 Remerciements
Nous remercions notre encadrant pour son accompagnement et ses orientations méthodologiques.
Nous remercions également l’équipe du projet Royal Plaza pour la qualité de leur structuration, qui a servi de référence pour l’organisation de ce document.
