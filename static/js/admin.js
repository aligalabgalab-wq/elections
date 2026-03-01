// static/js/admin.js - Fonctions spécifiques aux administrateurs

document.addEventListener('DOMContentLoaded', function() {
    // ========== TABLEAU DE BORD ADMIN ==========
    
    // Initialiser les graphiques du dashboard
    initializeAdminCharts();
    
    // Mettre à jour les statistiques en temps réel
    startAdminLiveUpdates();
    
    // ========== GESTION DES UTILISATEURS ==========
    
    // Recherche d'utilisateurs
    const userSearchInput = document.getElementById('userSearch');
    if (userSearchInput) {
        const userTableBody = document.getElementById('userTableBody');
        
        userSearchInput.addEventListener('input', function() {
            const searchTerm = this.value.toLowerCase();
            const rows = userTableBody.querySelectorAll('tr');
            
            rows.forEach(row => {
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(searchTerm) ? '' : 'none';
            });
        });
    }
    
    // Actions sur les utilisateurs
    document.querySelectorAll('[data-user-action]').forEach(button => {
        button.addEventListener('click', function() {
            const action = this.dataset.userAction;
            const userId = this.dataset.userId;
            const userName = this.dataset.userName;
            
            performUserAction(action, userId, userName);
        });
    });
    
    // ========== GESTION DES CANDIDATS ==========
    
    // Vérification d'éligibilité
    const checkEligibilityBtns = document.querySelectorAll('.check-eligibility');
    checkEligibilityBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const candidateId = this.dataset.candidateId;
            checkCandidateEligibility(candidateId);
        });
    });
    
    // Approuver/Rejeter des candidats
    const candidateActionBtns = document.querySelectorAll('[data-candidate-action]');
    candidateActionBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const action = this.dataset.candidateAction;
            const candidateId = this.dataset.candidateId;
            const candidateName = this.dataset.candidateName;
            
            performCandidateAction(action, candidateId, candidateName);
        });
    });
    
    // ========== GESTION DES ANNONCES ==========
    
    // Éditeur d'annonces
    const announcementEditor = document.getElementById('announcementContent');
    if (announcementEditor) {
        // Initialiser l'éditeur de texte riche
        if (typeof tinymce !== 'undefined') {
            tinymce.init({
                selector: '#announcementContent',
                height: 300,
                menubar: false,
                plugins: [
                    'advlist autolink lists link charmap print preview anchor',
                    'searchreplace visualblocks code fullscreen',
                    'insertdatetime media table paste code help wordcount'
                ],
                toolbar: 'undo redo | formatselect | ' +
                         'bold italic underline | alignleft aligncenter ' +
                         'alignright alignjustify | bullist numlist outdent indent | ' +
                         'removeformat | help'
            });
        }
    }
    
    // Programmation d'annonces
    const scheduleAnnouncementBtn = document.getElementById('scheduleAnnouncement');
    if (scheduleAnnouncementBtn) {
        scheduleAnnouncementBtn.addEventListener('click', function() {
            const scheduleModal = new bootstrap.Modal(
                document.getElementById('scheduleModal')
            );
            scheduleModal.show();
        });
    }
    
    // ========== PARAMÈTRES DE L'ÉLECTION ==========
    
    // Validation des dates
    const electionDatesForm = document.getElementById('electionDatesForm');
    if (electionDatesForm) {
        const dateInputs = electionDatesForm.querySelectorAll('input[type="datetime-local"]');
        
        dateInputs.forEach(input => {
            input.addEventListener('change', validateElectionDates);
        });
        
        function validateElectionDates() {
            const registrationStart = new Date(document.getElementById('registration_start').value);
            const registrationEnd = new Date(document.getElementById('registration_end').value);
            const votingStart = new Date(document.getElementById('voting_start').value);
            const votingEnd = new Date(document.getElementById('voting_end').value);
            
            let isValid = true;
            let errorMessage = '';
            
            // Validation des dates
            if (registrationStart >= registrationEnd) {
                errorMessage = 'La date de fin des inscriptions doit être après la date de début';
                isValid = false;
            } else if (registrationEnd >= votingStart) {
                errorMessage = 'Le vote doit commencer après la fin des inscriptions';
                isValid = false;
            } else if (votingStart >= votingEnd) {
                errorMessage = 'La date de fin du vote doit être après la date de début';
                isValid = false;
            }
            
            // Afficher l'erreur si nécessaire
            const errorElement = document.getElementById('dateValidationError');
            if (!isValid) {
                errorElement.textContent = errorMessage;
                errorElement.classList.remove('d-none');
            } else {
                errorElement.classList.add('d-none');
            }
            
            return isValid;
        }
    }
    
    // ========== RÉSULTATS ET AUDIT ==========
    
    // Initialiser le graphique des résultats détaillés
    const detailedResultsChart = document.getElementById('detailedResultsChart');
    if (detailedResultsChart) {
        initializeDetailedResultsChart();
    }
    
    // Exporter les résultats
    const exportResultsBtns = document.querySelectorAll('[data-export-results]');
    exportResultsBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const format = this.dataset.exportResults;
            exportElectionResults(format);
        });
    });
    
    // ========== FONCTIONS UTILITAIRES ==========
    
    function initializeAdminCharts() {
        // Graphique d'activité
        const activityChartCanvas = document.getElementById('activityChart');
        if (activityChartCanvas) {
            const ctx = activityChartCanvas.getContext('2d');
            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: JSON.parse(activityChartCanvas.dataset.labels || '[]'),
                    datasets: [{
                        label: 'Connexions',
                        data: JSON.parse(activityChartCanvas.dataset.logins || '[]'),
                        borderColor: '#0066b3',
                        backgroundColor: 'rgba(0, 102, 179, 0.1)',
                        fill: true,
                        tension: 0.4
                    }, {
                        label: 'Votes',
                        data: JSON.parse(activityChartCanvas.dataset.votes || '[]'),
                        borderColor: '#12ad2b',
                        backgroundColor: 'rgba(18, 173, 43, 0.1)',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    interaction: {
                        mode: 'index',
                        intersect: false
                    },
                    scales: {
                        x: {
                            display: true,
                            title: {
                                display: true,
                                text: 'Heure'
                            }
                        },
                        y: {
                            display: true,
                            title: {
                                display: true,
                                text: 'Nombre'
                            },
                            beginAtZero: true
                        }
                    }
                }
            });
        }
        
        // Graphique de répartition des rôles
        const rolesChartCanvas = document.getElementById('rolesChart');
        if (rolesChartCanvas) {
            const ctx = rolesChartCanvas.getContext('2d');
            new Chart(ctx, {
                type: 'pie',
                data: {
                    labels: ['Électeurs', 'Candidats', 'Administrateurs'],
                    datasets: [{
                        data: JSON.parse(rolesChartCanvas.dataset.counts || '[0, 0, 0]'),
                        backgroundColor: [
                            '#0066b3', // Électeurs
                            '#12ad2b', // Candidats
                            '#d21034'  // Administrateurs
                        ]
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: {
                            position: 'bottom'
                        }
                    }
                }
            });
        }
    }
    
    function startAdminLiveUpdates() {
        // Mettre à jour les statistiques toutes les 30 secondes
        setInterval(updateAdminStats, 30000);
        updateAdminStats(); // Mettre à jour immédiatement
    }
    
    async function updateAdminStats() {
        try {
            const response = await fetch('/api/admin/stats/live');
            const data = await response.json();
            
            // Mettre à jour les cartes de statistiques
            updateStatCard('totalVoters', data.total_voters);
            updateStatCard('totalCandidates', data.total_candidates);
            updateStatCard('totalVotes', data.total_votes);
            updateStatCard('participationRate', data.participation_rate + '%');
            
            // Mettre à jour la dernière activité
            const lastActivityElement = document.getElementById('lastActivity');
            if (lastActivityElement) {
                lastActivityElement.innerHTML = `
                    <i class="ri-user-line me-2"></i>
                    ${data.last_activity.user} - 
                    <span class="text-muted">${data.last_activity.time}</span>
                `;
            }
            
        } catch (error) {
            console.error('Erreur lors de la mise à jour:', error);
        }
    }
    
    function updateStatCard(elementId, value) {
        const element = document.getElementById(elementId);
        if (element) {
            const currentValue = parseInt(element.textContent.replace(/\D/g, '')) || 0;
            const newValue = parseInt(value) || value;
            
            if (typeof newValue === 'number') {
                animateCounter(element, currentValue, newValue);
            } else {
                element.textContent = value;
            }
        }
    }
    
    function performUserAction(action, userId, userName) {
        let title, text, confirmText;
        
        switch (action) {
            case 'activate':
                title = 'Activer l\'utilisateur';
                text = `Voulez-vous activer le compte de ${userName} ?`;
                confirmText = 'Activer';
                break;
            case 'deactivate':
                title = 'Désactiver l\'utilisateur';
                text = `Voulez-vous désactiver le compte de ${userName} ?`;
                confirmText = 'Désactiver';
                break;
            case 'delete':
                title = 'Supprimer l\'utilisateur';
                text = `Voulez-vous supprimer définitivement le compte de ${userName} ?`;
                confirmText = 'Supprimer';
                break;
            case 'reset_password':
                title = 'Réinitialiser le mot de passe';
                text = `Voulez-vous réinitialiser le mot de passe de ${userName} ?`;
                confirmText = 'Réinitialiser';
                break;
        }
        
        confirmAction(title, text, confirmText).then((result) => {
            if (result.isConfirmed) {
                fetch(`/admin/users/${userId}/${action}`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCSRFToken()
                    }
                })
                .then(response => response.json())
                .then(data => {
                    showToast(data.message, 'success');
                    setTimeout(() => location.reload(), 1500);
                })
                .catch(error => {
                    console.error('Erreur:', error);
                    showToast('Erreur lors de l\'action', 'error');
                });
            }
        });
    }
    
    function checkCandidateEligibility(candidateId) {
        const eligibilityBtn = document.querySelector(`[data-candidate-id="${candidateId}"]`);
        if (eligibilityBtn) {
            eligibilityBtn.disabled = true;
            eligibilityBtn.innerHTML = `
                <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                Vérification...
            `;
        }
        
        fetch(`/admin/candidates/${candidateId}/check-eligibility`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken()
            }
        })
        .then(response => response.json())
        .then(data => {
            showToast(data.message, data.success ? 'success' : 'error');
            
            if (eligibilityBtn) {
                eligibilityBtn.disabled = false;
                eligibilityBtn.innerHTML = `
                    <i class="ri-check-double-line me-2"></i>
                    Vérifier l'éligibilité
                `;
                
                // Mettre à jour l'affichage
                const eligibilityBadge = document.querySelector(`[data-eligibility-badge="${candidateId}"]`);
                if (eligibilityBadge) {
                    eligibilityBadge.className = `badge bg-${data.is_eligible ? 'success' : 'danger'}`;
                    eligibilityBadge.textContent = data.is_eligible ? 'Éligible' : 'Non éligible';
                }
            }
        })
        .catch(error => {
            console.error('Erreur:', error);
            showToast('Erreur lors de la vérification', 'error');
            
            if (eligibilityBtn) {
                eligibilityBtn.disabled = false;
                eligibilityBtn.innerHTML = `
                    <i class="ri-check-double-line me-2"></i>
                    Vérifier l'éligibilité
                `;
            }
        });
    }
    
    function performCandidateAction(action, candidateId, candidateName) {
        let title, text, confirmText;
        
        switch (action) {
            case 'approve':
                title = 'Approuver la candidature';
                text = `Voulez-vous approuver la candidature de ${candidateName} ?`;
                confirmText = 'Approuver';
                break;
            case 'reject':
                title = 'Rejeter la candidature';
                text = `Voulez-vous rejeter la candidature de ${candidateName} ?`;
                confirmText = 'Rejeter';
                break;
            case 'suspend':
                title = 'Suspendre la candidature';
                text = `Voulez-vous suspendre la candidature de ${candidateName} ?`;
                confirmText = 'Suspendre';
                break;
        }
        
        confirmAction(title, text, confirmText).then((result) => {
            if (result.isConfirmed) {
                fetch(`/admin/candidates/${candidateId}/${action}`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCSRFToken()
                    }
                })
                .then(response => response.json())
                .then(data => {
                    showToast(data.message, 'success');
                    setTimeout(() => location.reload(), 1500);
                })
                .catch(error => {
                    console.error('Erreur:', error);
                    showToast('Erreur lors de l\'action', 'error');
                });
            }
        });
    }
    
    function initializeDetailedResultsChart() {
        const ctx = detailedResultsChart.getContext('2d');
        
        // Données des candidats
        const candidates = JSON.parse(detailedResultsChart.dataset.candidates || '[]');
        const votes = JSON.parse(detailedResultsChart.dataset.votes || '[]');
        const colors = JSON.parse(detailedResultsChart.dataset.colors || '[]');
        
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: candidates,
                datasets: [{
                    label: 'Nombre de votes',
                    data: votes,
                    backgroundColor: colors,
                    borderColor: colors.map(c => darkenColor(c, 20)),
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const total = votes.reduce((a, b) => a + b, 0);
                                const percentage = total > 0 ? ((context.raw / total) * 100).toFixed(1) : 0;
                                return `${context.raw} votes (${percentage}%)`;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                return value.toLocaleString();
                            }
                        }
                    },
                    x: {
                        ticks: {
                            maxRotation: 45,
                            minRotation: 45
                        }
                    }
                }
            }
        });
    }
    
    function exportElectionResults(format) {
        confirmAction(
            'Exporter les résultats',
            `Voulez-vous exporter les résultats complets au format ${format.toUpperCase()} ?`
        ).then((result) => {
            if (result.isConfirmed) {
                window.location.href = `/admin/results/export/${format}`;
            }
        });
    }
    
    function getCSRFToken() {
        const cookieValue = document.cookie
            .split('; ')
            .find(row => row.startsWith('csrf_token='))
            ?.split('=')[1];
        return cookieValue || '';
    }
    
    function darkenColor(color, percent) {
        // Fonction utilitaire pour assombrir une couleur
        if (color.startsWith('rgb')) {
            const matches = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
            if (matches) {
                const r = Math.max(0, parseInt(matches[1]) - percent);
                const g = Math.max(0, parseInt(matches[2]) - percent);
                const b = Math.max(0, parseInt(matches[3]) - percent);
                return `rgb(${r}, ${g}, ${b})`;
            }
        }
        return color;
    }
    
    // ========== AUDIT ET JOURNALISATION ==========
    
    // Filtrer les logs d'audit
    const auditLogFilters = document.querySelectorAll('[data-audit-filter]');
    auditLogFilters.forEach(filter => {
        filter.addEventListener('change', function() {
            const action = this.dataset.auditFilter;
            const value = this.value;
            
            fetch(`/admin/audit-logs/filter?${action}=${value}`)
                .then(response => response.text())
                .then(html => {
                    document.getElementById('auditLogsTable').innerHTML = html;
                })
                .catch(error => {
                    console.error('Erreur:', error);
                    showToast('Erreur lors du filtrage', 'error');
                });
        });
    });
    
    // Exporter les logs d'audit
    const exportAuditLogsBtn = document.getElementById('exportAuditLogs');
    if (exportAuditLogsBtn) {
        exportAuditLogsBtn.addEventListener('click', function() {
            const format = this.dataset.format || 'csv';
            
            confirmAction(
                'Exporter les logs d\'audit',
                `Voulez-vous exporter les logs d'audit au format ${format.toUpperCase()} ?`
            ).then((result) => {
                if (result.isConfirmed) {
                    window.location.href = `/admin/audit-logs/export/${format}`;
                }
            });
        });
    }
    
    // ========== SAUVEGARDE ET RESTAURATION ==========
    
    // Sauvegarde manuelle
    const backupBtn = document.getElementById('manualBackup');
    if (backupBtn) {
        backupBtn.addEventListener('click', function() {
            this.disabled = true;
            this.innerHTML = `
                <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                Sauvegarde en cours...
            `;
            
            fetch('/admin/backup/create', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCSRFToken()
                }
            })
            .then(response => response.json())
            .then(data => {
                showToast(data.message, 'success');
                this.disabled = false;
                this.innerHTML = '<i class="ri-save-line me-2"></i> Sauvegarder';
            })
            .catch(error => {
                console.error('Erreur:', error);
                showToast('Erreur lors de la sauvegarde', 'error');
                this.disabled = false;
                this.innerHTML = '<i class="ri-save-line me-2"></i> Sauvegarder';
            });
        });
    }
    
    // Restauration
    const restoreFileInput = document.getElementById('restoreFile');
    if (restoreFileInput) {
        restoreFileInput.addEventListener('change', function() {
            if (!this.files.length) return;
            
            const file = this.files[0];
            const formData = new FormData();
            formData.append('backup_file', file);
            
            confirmAction(
                'Restaurer la sauvegarde',
                'Voulez-vous restaurer cette sauvegarde ? Cette action remplacera toutes les données actuelles.'
            ).then((result) => {
                if (result.isConfirmed) {
                    fetch('/admin/backup/restore', {
                        method: 'POST',
                        body: formData
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            showToast('Restauration réussie', 'success');
                            setTimeout(() => location.reload(), 2000);
                        } else {
                            showToast(data.message, 'error');
                        }
                    })
                    .catch(error => {
                        console.error('Erreur:', error);
                        showToast('Erreur lors de la restauration', 'error');
                    });
                }
            });
        });
    }
});