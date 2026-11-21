"""Tiny built-in translation table for the GUI and tray menu.

Only three languages are supported, so this stays a plain dict: no external
packages, no locale files to ship, and no work for the tray-only mode.
"""
from __future__ import annotations

LANGUAGES = ("en", "fr", "ar")
DISPLAY = {
    "en": "English",
    "fr": "Français",
    "ar": "العربية",
}
RTL_LANGUAGES = frozenset(("ar",))

TEXT: dict[str, dict[str, str]] = {
    "fr": {
        # settings window
        "Hotkey — Settings": "Hotkey — Paramètres",
        "Open hotkeys.json": "Ouvrir hotkeys.json",
        "Open hotkeys.json in your default editor": "Ouvrir hotkeys.json dans l'éditeur par défaut",
        "Reload": "Recharger",
        "Reload from disk (discards unsaved UI state)": "Recharger depuis le disque (annule les modifications non enregistrées)",
        "Open file": "Ouvrir le fichier",
        "SHORTCUTS": "RACCOURCIS",
        "+  Add hotkey": "+  Ajouter un raccourci",
        "Add hotkey": "Ajouter un raccourci",
        "Edit": "Modifier",
        "Delete": "Supprimer",
        "Double-click a row to edit": "Double-cliquez sur une ligne pour modifier",
        "Profile:": "Profil :",
        "(none)": "(aucun)",
        "Shortcut": "Raccourci",
        "Action": "Action",
        "Detail": "Détail",
        "State": "État",
        "No hotkeys yet.\nClick “+ Add hotkey” or press Ctrl+N to create one.":
            "Aucun raccourci.\nCliquez sur « + Ajouter un raccourci » ou appuyez sur Ctrl+N.",
        "Start with Windows": "Démarrer avec Windows",
        "Run this app automatically when you sign in": "Lancer cette application automatiquement à la connexion",
        "Language": "Langue",
        "Interface language": "Langue de l'interface",
        "Language settings": "Paramètres de langue",
        "Quick settings": "Paramètres rapides",
        "Show notifications": "Afficher les notifications",
        "Notifications enabled": "Notifications activées",
        "Notifications disabled": "Notifications désactivées",
        "Could not save preferences:\n{error}":
            "Impossible d'enregistrer les préférences :\n{error}",
        "Apply": "Appliquer",
        "{count} shortcuts · {enabled} active": "{count} raccourcis · {enabled} actifs",
        " · {count} per-app": " · {count} par application",
        " · {count} profiled": " · {count} avec profil",
        "On": "Actif",
        "Off": "Inactif",
        "Saved to hotkeys.json · {count} active": "Enregistré dans hotkeys.json · {count} actifs",
        "Saved · hotkeys reloaded": "Enregistré · raccourcis rechargés",
        "Could not save hotkeys.json:\n{error}": "Impossible d'enregistrer hotkeys.json :\n{error}",
        "Reloaded from disk": "Rechargé depuis le disque",
        "Fired: {name}": "Déclenché : {name}",
        "Select a hotkey first": "Sélectionnez d'abord un raccourci",
        "Delete hotkey": "Supprimer le raccourci",
        "Delete {name} ({label})?": "Supprimer {name} ({label}) ?",
        "Added {name}": "Ajouté : {name}",
        "Updated {name}": "Modifié : {name}",
        "Deleted {name}": "Supprimé : {name}",
        "Autostart enabled": "Démarrage automatique activé",
        "Autostart disabled": "Démarrage automatique désactivé",
        "Could not update autostart:\n{error}": "Impossible de modifier le démarrage automatique :\n{error}",
        "⚠ {count} config problem — some hotkeys may be inactive":
            "⚠ {count} problème de configuration — certains raccourcis peuvent être inactifs",
        "⚠ {count} config problems — some hotkeys may be inactive":
            "⚠ {count} problèmes de configuration — certains raccourcis peuvent être inactifs",
        "Language set to {language}": "Langue définie sur {language}",
        "Could not save language:\n{error}": "Impossible d'enregistrer la langue :\n{error}",
        "chord": "accord",
        "Key info": "Infos touche",
        "Where": "Où",
        "Target / note": "Cible / note",
        "All apps": "Toutes les applications",
        "Leader · {count} steps": "Séquence · {count} étapes",
        "Chord · {count} keys": "Accord · {count} touches",
        "{count} steps": "{count} étapes",
        "Speed {speed}": "Vitesse {speed}",

        # editor
        "New hotkey": "Nouveau raccourci",
        "Edit hotkey": "Modifier le raccourci",
        "press a key or mouse button": "appuyez sur une touche ou un bouton de la souris",
        "Clear": "Effacer",
        "Type": "Saisir",
        "Capture": "Capturer",
        "Steps": "Étapes",
        "Single": "Simple",
        "Trigger": "Déclencheur",
        "single keys only": "touches simples uniquement",
        "Instant (press)": "Immédiat (pression)",
        "Double click": "Double clic",
        "On release (tap)": "Au relâchement (tap)",
        "Long press (hold)": "Appui long (maintien)",
        "Only in app": "Uniquement dans l'application",
        "blank = every app": "vide = toutes les applications",
        "Detect": "Détecter",
        "Any": "Toutes",
        "Profiles": "Profils",
        "comma = only in those profiles": "séparés par des virgules = uniquement dans ces profils",
        "Target": "Cible",
        "Description": "Description",
        "optional": "facultatif",
        "Advanced JSON": "JSON avancé",
        "Enabled": "Activé",
        "Cancel": "Annuler",
        "Save hotkey": "Enregistrer le raccourci",
        "Uses the current clipboard contents.": "Utilise le contenu actuel du presse-papiers.",
        "Value": "Valeur",
        "Steps: {count}": "{count} étapes",
        "Record": "Enregistrer",
        "Speed:": "Vitesse :",
        "Mouse {button} ({x},{y}) -> ({x2},{y2})   (+{wait} ms)":
            "Souris {button} ({x},{y}) -> ({x2},{y2})   (+{wait} ms)",
        "Clear macro": "Effacer le macro",
        "Remove all recorded steps?": "Supprimer toutes les étapes enregistrées ?",
        "Record macro": "Enregistrer le macro",
        "Replace the existing recorded steps?": "Remplacer les étapes déjà enregistrées ?",
        "Could not start recording:\n{error}": "Impossible de démarrer l'enregistrement :\n{error}",
        "● Recording macro — press Esc to stop": "● Enregistrement du macro — Échap pour arrêter",
        "● Recording macro — {count} steps — Esc to stop":
            "● Enregistrement du macro — {count} étapes — Échap pour arrêter",
        "Switch to the target app — detecting in {count} s…":
            "Passez à l'application cible — détection dans {count} s…",
        "Bound to {exe}": "Lié à {exe}",
        "Could not detect the app — type its .exe name":
            "Impossible de détecter l'application — saisissez son nom .exe",
        "Press a key or mouse button to capture it…": "Appuyez sur une touche ou un bouton pour la capturer…",
        "Leader sequence · {count} steps": "Séquence préfixe · {count} étapes",
        "a leader sequence needs at least two steps": "une séquence préfixe doit comporter au moins deux étapes",
        "This action needs a value.": "Cette action nécessite une valeur.",
        "Record at least one step for the macro.": "Enregistrez au moins une étape pour le macro.",
        "is already used by \"{label}\"{where}": "est déjà utilisé par « {label} »{where}",
        "(in {apps})": "(dans {apps})",
        "already does \"{what}\" ({label}) - same button, same action":
            "fait déjà « {what} » ({label}) - même touche, même action",

        # action labels
        "Open": "Ouvrir",
        "Run": "Exécuter",
        "Keys": "Touches",
        "Copy": "Copier",
        "Paste": "Coller",
        "Media": "Média",
        "Window": "Fenêtre",
        "System": "Système",
        "App": "Application",
        "Summon": "Appeler",
        "Macro": "Macro",
        "Profile": "Profil",

        # action editor fields and hints
        "Open app, file, folder or URL":
            "Ouvrir une application, un fichier, un dossier ou une URL",
        "notepad.exe, %USERPROFILE%\\Desktop, https://example.com":
            "notepad.exe, %USERPROFILE%\\Desktop, https://example.com",
        "Run command (no window)": "Exécuter une commande (sans fenêtre)",
        "Command line": "Ligne de commande",
        "python -m http.server 8000  (optional: cwd)":
            "python -m http.server 8000  (facultatif : cwd)",
        "Type text into the active app": "Saisir du texte dans l'application active",
        "Text": "Texte",
        "Hello {user}! Today is {date}.  Tokens: {clip} {time} {newline} {tab}":
            "Bonjour {user} ! Nous sommes le {date}.  Jetons : {clip} {time} {newline} {tab}",
        "Send keystrokes": "Envoyer des touches",
        "ctrl+v  or  ctrl+a, delete  (comma = sequence)":
            "ctrl+v  ou  ctrl+a, delete  (virgule = séquence)",
        "Copy text to clipboard": "Copier du texte dans le presse-papiers",
        "Copied at {time} from {computer}": "Copié à {time} depuis {computer}",
        "Type the clipboard as plain text": "Saisir le presse-papiers en texte brut",
        "Works in terminals, RDP and apps that block Ctrl+V":
            "Fonctionne dans les terminaux, le RDP et les applications qui bloquent Ctrl+V",
        "Media / volume key": "Touche média / volume",
        "Operation": "Opération",
        "Window control": "Contrôle de fenêtre",
        "System command": "Commande système",
        "Hotkey app command": "Commande de l'application Hotkey",
        "Summon / toggle a window": "Appeler / basculer une fenêtre",
        "chrome.exe, notepad.exe — focuses, minimizes or launches it":
            "chrome.exe, notepad.exe — active, minimise ou lance l'application",
        "Play a recorded macro": "Lire un macro enregistré",
        "Recorded in the editor; keys only, with timing":
            "Enregistré dans l'éditeur ; touches uniquement, avec temporisation",
        "Switch hotkey profile": "Changer de profil de raccourcis",
        "Work, Gaming, or 'next' to cycle":
            "Work, Gaming ou 'next' pour faire défiler",

        # macro control window
        "Hotkey · Macro control": "Hotkey · Contrôle du macro",
        "Macro control": "Contrôle du macro",
        "set up · then run": "configurez · puis exécutez",
        "Close": "Fermer",
        "LOADED MACRO": "MACRO CHARGÉ",
        "Times": "Nombre de fois",
        "how many runs": "nombre d'exécutions",
        "Speed": "Vitesse",
        "live": "en direct",
        "Start with": "Démarrer avec",
        "Stop with": "Arrêter avec",
        "Set key": "Définir la touche",
        "Start": "Démarrer",
        "Stop": "Arrêter",
        "click, then press a key · Esc clears": "cliquez, puis appuyez sur une touche · Échap efface",
        "Press a key…": "Appuyez sur une touche…",
        "Press a key or mouse button anywhere…": "Appuyez n'importe où sur une touche ou un bouton de souris…",
        "That key is not safe globally — try a combo": "Cette touche n'est pas sûre globalement — essayez une combinaison",
        "Press a key or mouse button…": "Appuyez sur une touche ou un bouton de souris…",
        "Start: {combo}": "Démarrer : {combo}",
        "Stop: {combo}": "Arrêter : {combo}",
        "Set start key": "Définir la touche de démarrage",
        "Set stop key": "Définir la touche d'arrêt",
        "{label} key cleared": "Touche {label} effacée",
        "{label} key set to {combo}": "Touche {label} définie sur {combo}",
        " · chord": " · accord",
        "Capture failed: {error}": "Échec de la capture : {error}",
        "▶  Run / Repeat": "▶  Exécuter / Répéter",
        "Hide this window; the tray menu can show it again": "Masque cette fenêtre ; le menu de la barre des tâches peut la réafficher",
        "Choose a global key that starts the loaded macro": "Choisissez une touche globale qui démarre le macro chargé",
        "Choose a global key that stops the current run": "Choisissez une touche globale qui arrête l'exécution en cours",
        "How many full runs to play (can change while running)": "Nombre d'exécutions complètes (modifiable pendant l'exécution)",
        "Playback speed (can change while running)": "Vitesse de lecture (modifiable pendant l'exécution)",
        "Play the loaded macro with the settings above": "Joue le macro chargé avec les réglages ci-dessus",
        "Finish the current run, then stop": "Termine l'exécution en cours, puis s'arrête",
        "Abort immediately": "Interrompt immédiatement",
        "Ready": "Prêt",
        "Cancelling…": "Annulation…",
        "Finishing run…": "Fin de l'exécution…",
        "Running": "En cours",
        "Ready — press Run": "Prêt — appuyez sur Exécuter",
        "run {run}/{total}   ·   step {step}/{steps}": "exécution {run}/{total}   ·   étape {step}/{steps}",
        "{steps} steps   ·   {times} runs   ·   {speed} speed": "{steps} étapes   ·   {times} exécutions   ·   vitesse {speed}",
        "no macro loaded — press a macro hotkey": "aucun macro chargé — appuyez sur un raccourci macro",

        # tray
        "    ...{count} more (see settings)": "    ...{count} de plus (voir les paramètres)",
        "    no hotkeys configured": "    aucun raccourci configuré",
        "Next profile": "Profil suivant",
        "Profiles": "Profils",
        "Show / hide macro controls": "Afficher / masquer les contrôles du macro",
        "Hotkey settings...": "Paramètres de Hotkey...",
        "Reload hotkeys": "Recharger les raccourcis",
        "Suspend all hotkeys": "Suspendre tous les raccourcis",
        "Open log": "Ouvrir le journal",
        "Quit": "Quitter",
        "Profile: {name}": "Profil : {name}",
        "Reloaded: {count} hotkeys active": "Rechargé : {count} raccourcis actifs",
        "No macro hotkey is configured": "Aucun raccourci macro n'est configuré",
        "Cannot save": "Impossible d'enregistrer",
        "Config problem": "Problème de configuration",
        "Some hotkeys are unavailable": "Certains raccourcis sont indisponibles",
        "Macro": "Macro",
        "Starts with Windows": "Démarre avec Windows",
        "Autostart disabled": "Démarrage automatique désactivé",
        "{count} active": "{count} actifs",
        "paused": "en pause",
        "{count} hotkeys active": "{count} raccourcis actifs",
        "{count} hotkeys active. Double-click the tray icon to edit them.":
            "{count} raccourcis actifs. Double-cliquez sur l'icône de la barre des tâches pour les modifier.",
        "{name} is already used by another app":
            "{name} est déjà utilisé par une autre application",
        "Long-press/chords disabled": "Appui long / accords désactivés",
        "Mouse hotkeys disabled": "Raccourcis souris désactivés",
        "Leader key": "Touche préfixe",
        "Cannot open": "Impossible d'ouvrir",
        "{name} failed": "Échec de {name}",
        "paused - all hotkeys are free for other apps":
            "en pause - tous les raccourcis sont libres pour les autres applications",
        "resumed - {count} hotkeys active":
            "repris - {count} raccourcis actifs",
    },
    "ar": {
        # settings window
        "Hotkey — Settings": "Hotkey — الإعدادات",
        "Open hotkeys.json": "فتح hotkeys.json",
        "Open hotkeys.json in your default editor": "فتح hotkeys.json في المحرر الافتراضي",
        "Reload": "إعادة تحميل",
        "Reload from disk (discards unsaved UI state)": "إعادة التحميل من القرص (يلغي التغييرات غير المحفوظة)",
        "Open file": "فتح الملف",
        "SHORTCUTS": "الاختصارات",
        "+  Add hotkey": "+  إضافة اختصار",
        "Add hotkey": "إضافة اختصار",
        "Edit": "تعديل",
        "Delete": "حذف",
        "Double-click a row to edit": "انقر نقرًا مزدوجًا على صف للتعديل",
        "Profile:": "الملف الشخصي:",
        "(none)": "(لا شيء)",
        "Shortcut": "الاختصار",
        "Action": "الإجراء",
        "Detail": "التفاصيل",
        "State": "الحالة",
        "No hotkeys yet.\nClick “+ Add hotkey” or press Ctrl+N to create one.":
            "لا توجد اختصارات بعد.\nانقر «+ إضافة اختصار» أو اضغط Ctrl+N لإنشاء واحد.",
        "Start with Windows": "البدء مع Windows",
        "Run this app automatically when you sign in": "تشغيل هذا التطبيق تلقائيًا عند تسجيل الدخول",
        "Language": "اللغة",
        "Interface language": "لغة الواجهة",
        "Language settings": "إعدادات اللغة",
        "Quick settings": "إعدادات سريعة",
        "Show notifications": "إظهار الإشعارات",
        "Notifications enabled": "الإشعارات مفعّلة",
        "Notifications disabled": "الإشعارات معطّلة",
        "Could not save preferences:\n{error}":
            "تعذر حفظ التفضيلات:\n{error}",
        "Apply": "تطبيق",
        "{count} shortcuts · {enabled} active": "{count} اختصارات · {enabled} نشطة",
        " · {count} per-app": " · {count} خاصة بتطبيق",
        " · {count} profiled": " · {count} مرتبطة بملف شخصي",
        "On": "مفعّل",
        "Off": "معطّل",
        "Saved to hotkeys.json · {count} active": "تم الحفظ في hotkeys.json · {count} نشطة",
        "Saved · hotkeys reloaded": "تم الحفظ · تمت إعادة تحميل الاختصارات",
        "Could not save hotkeys.json:\n{error}": "تعذر حفظ hotkeys.json:\n{error}",
        "Reloaded from disk": "تمت إعادة التحميل من القرص",
        "Fired: {name}": "تم التفعيل: {name}",
        "Select a hotkey first": "اختر اختصارًا أولًا",
        "Delete hotkey": "حذف الاختصار",
        "Delete {name} ({label})?": "حذف {name} ({label})؟",
        "Added {name}": "تمت إضافة {name}",
        "Updated {name}": "تم تعديل {name}",
        "Deleted {name}": "تم حذف {name}",
        "Autostart enabled": "تم تفعيل البدء التلقائي",
        "Autostart disabled": "تم تعطيل البدء التلقائي",
        "Could not update autostart:\n{error}": "تعذر تغيير البدء التلقائي:\n{error}",
        "⚠ {count} config problem — some hotkeys may be inactive":
            "⚠ {count} مشكلة في الإعدادات — قد تكون بعض الاختصارات غير نشطة",
        "⚠ {count} config problems — some hotkeys may be inactive":
            "⚠ {count} مشكلات في الإعدادات — قد تكون بعض الاختصارات غير نشطة",
        "Language set to {language}": "تم ضبط اللغة على {language}",
        "Could not save language:\n{error}": "تعذر حفظ اللغة:\n{error}",
        "chord": "تشارك",
        "Key info": "معلومات المفتاح",
        "Where": "المكان",
        "Target / note": "الهدف / ملاحظة",
        "All apps": "جميع التطبيقات",
        "Leader · {count} steps": "تسلسل بادئة · {count} خطوة",
        "Chord · {count} keys": "تشارك · {count} مفاتيح",
        "{count} steps": "{count} خطوة",
        "Speed {speed}": "السرعة {speed}",

        # editor
        "New hotkey": "اختصار جديد",
        "Edit hotkey": "تعديل الاختصار",
        "press a key or mouse button": "اضغط مفتاحًا أو زر فأرة",
        "Clear": "مسح",
        "Type": "كتابة",
        "Capture": "التقاط",
        "Steps": "خطوات",
        "Single": "مفرد",
        "Trigger": "التحفيز",
        "single keys only": "المفاتيح المفردة فقط",
        "Instant (press)": "فوري (ضغط)",
        "Double click": "نقرة مزدوجة",
        "On release (tap)": "عند التحرير (نقرة)",
        "Long press (hold)": "ضغط مطوّل",
        "Only in app": "فقط في التطبيق",
        "blank = every app": "فارغ = جميع التطبيقات",
        "Detect": "اكتشاف",
        "Any": "أي",
        "Profiles": "الملفات الشخصية",
        "comma = only in those profiles": "افصل بفاصلة = فقط في هذه الملفات",
        "Target": "الهدف",
        "Description": "الوصف",
        "optional": "اختياري",
        "Advanced JSON": "JSON متقدم",
        "Enabled": "مفعّل",
        "Cancel": "إلغاء",
        "Save hotkey": "حفظ الاختصار",
        "Uses the current clipboard contents.": "يستخدم محتوى الحافظة الحالي.",
        "Value": "القيمة",
        "Steps: {count}": "{count} خطوة",
        "Record": "تسجيل",
        "Speed:": "السرعة:",
        "Mouse {button} ({x},{y}) -> ({x2},{y2})   (+{wait} ms)":
            "الفأرة {button} ({x},{y}) -> ({x2},{y2})   (+{wait} ملّي ثانية)",
        "Clear macro": "مسح الماكرو",
        "Remove all recorded steps?": "حذف جميع الخطوات المسجلة؟",
        "Record macro": "تسجيل الماكرو",
        "Replace the existing recorded steps?": "استبدال الخطوات المسجلة حاليًا؟",
        "Could not start recording:\n{error}": "تعذر بدء التسجيل:\n{error}",
        "● Recording macro — press Esc to stop": "● جارٍ تسجيل الماكرو — اضغط Esc للإيقاف",
        "● Recording macro — {count} steps — Esc to stop":
            "● جارٍ تسجيل الماكرو — {count} خطوة — Esc للإيقاف",
        "Switch to the target app — detecting in {count} s…":
            "انتقل إلى التطبيق المستهدف — الكشف خلال {count} ث…",
        "Bound to {exe}": "مرتبط بـ {exe}",
        "Could not detect the app — type its .exe name":
            "تعذر كشف التطبيق — اكتب اسم ملف .exe",
        "Press a key or mouse button to capture it…": "اضغط مفتاحًا أو زر فأرة لتسجيله…",
        "Leader sequence · {count} steps": "تسلسل بادئة · {count} خطوة",
        "a leader sequence needs at least two steps": "تسلسل البادئة يحتاج خطوتين على الأقل",
        "This action needs a value.": "هذا الإجراء يحتاج قيمة.",
        "Record at least one step for the macro.": "سجّل خطوة واحدة على الأقل للماكرو.",
        "is already used by \"{label}\"{where}": "مستخدم بالفعل بواسطة « {label} »{where}",
        "(in {apps})": "(في {apps})",
        "already does \"{what}\" ({label}) - same button, same action":
            "ينفّذ بالفعل « {what} » ({label}) - نفس المفتاح، نفس الإجراء",

        # action labels
        "Open": "فتح",
        "Run": "تشغيل",
        "Keys": "مفاتيح",
        "Copy": "نسخ",
        "Paste": "لصق",
        "Media": "وسائط",
        "Window": "نافذة",
        "System": "النظام",
        "App": "تطبيق",
        "Summon": "استحضار",
        "Macro": "ماكرو",
        "Profile": "ملف شخصي",

        # action editor fields and hints
        "Open app, file, folder or URL":
            "فتح تطبيق أو ملف أو مجلد أو عنوان URL",
        "notepad.exe, %USERPROFILE%\\Desktop, https://example.com":
            "notepad.exe, %USERPROFILE%\\Desktop, https://example.com",
        "Run command (no window)": "تشغيل أمر (بدون نافذة)",
        "Command line": "سطر الأوامر",
        "python -m http.server 8000  (optional: cwd)":
            "python -m http.server 8000  (اختياري: cwd)",
        "Type text into the active app": "كتابة نص في التطبيق النشط",
        "Text": "نص",
        "Hello {user}! Today is {date}.  Tokens: {clip} {time} {newline} {tab}":
            "مرحبًا {user}! اليوم هو {date}.  الرموز: {clip} {time} {newline} {tab}",
        "Send keystrokes": "إرسال ضغطات المفاتيح",
        "ctrl+v  or  ctrl+a, delete  (comma = sequence)":
            "ctrl+v  أو  ctrl+a, delete  (الفاصلة = تسلسل)",
        "Copy text to clipboard": "نسخ نص إلى الحافظة",
        "Copied at {time} from {computer}": "تم النسخ في {time} من {computer}",
        "Type the clipboard as plain text": "كتابة محتوى الحافظة كنص عادي",
        "Works in terminals, RDP and apps that block Ctrl+V":
            "يعمل في الطرفيات و RDP والتطبيقات التي تحظر Ctrl+V",
        "Media / volume key": "مفتاح وسائط / صوت",
        "Operation": "العملية",
        "Window control": "التحكم بالنوافذ",
        "System command": "أمر النظام",
        "Hotkey app command": "أمر تطبيق Hotkey",
        "Summon / toggle a window": "استحضار نافذة أو التبديل إليها",
        "chrome.exe, notepad.exe — focuses, minimizes or launches it":
            "chrome.exe, notepad.exe — ينشّط أو يصغّر أو يشغّل التطبيق",
        "Play a recorded macro": "تشغيل ماكرو مسجّل",
        "Recorded in the editor; keys only, with timing":
            "مسجّل في المحرر؛ مفاتيح فقط، مع التوقيت",
        "Switch hotkey profile": "تبديل ملف اختصارات",
        "Work, Gaming, or 'next' to cycle":
            "Work أو Gaming أو 'next' للتدوير",

        # macro control window
        "Hotkey · Macro control": "Hotkey · التحكم بالماكرو",
        "Macro control": "التحكم بالماكرو",
        "set up · then run": "اضبط · ثم شغّل",
        "Close": "إغلاق",
        "LOADED MACRO": "الماكرو المحمّل",
        "Times": "عدد المرات",
        "how many runs": "عدد مرات التشغيل",
        "Speed": "السرعة",
        "live": "مباشر",
        "Start with": "البدء بـ",
        "Stop with": "الإيقاف بـ",
        "Set key": "تعيين مفتاح",
        "Start": "بدء",
        "Stop": "إيقاف",
        "click, then press a key · Esc clears": "انقر، ثم اضغط مفتاحًا · Esc يمسح",
        "Press a key…": "اضغط مفتاحًا…",
        "Press a key or mouse button anywhere…": "اضغط أي مفتاح أو زر فأرة في أي مكان…",
        "That key is not safe globally — try a combo": "هذا المفتاح غير آمن عالميًا — جرّب تركيبة",
        "Press a key or mouse button…": "اضغط مفتاحًا أو زر فأرة…",
        "Start: {combo}": "البدء: {combo}",
        "Stop: {combo}": "الإيقاف: {combo}",
        "Set start key": "تعيين مفتاح البدء",
        "Set stop key": "تعيين مفتاح الإيقاف",
        "{label} key cleared": "تم مسح مفتاح {label}",
        "{label} key set to {combo}": "تم ضبط مفتاح {label} على {combo}",
        " · chord": " · تشارك",
        "Capture failed: {error}": "فشل الالتقاط: {error}",
        "▶  Run / Repeat": "▶  تشغيل / تكرار",
        "Hide this window; the tray menu can show it again": "إخفاء هذه النافذة؛ يمكن لقائمة شريط المهام إظهارها مجددًا",
        "Choose a global key that starts the loaded macro": "اختر مفتاحًا عالميًا يبدأ الماكرو المحمّل",
        "Choose a global key that stops the current run": "اختر مفتاحًا عالميًا يوقف التشغيل الحالي",
        "How many full runs to play (can change while running)": "عدد مرات التشغيل الكاملة (قابل للتغيير أثناء التشغيل)",
        "Playback speed (can change while running)": "سرعة التشغيل (قابلة للتغيير أثناء التشغيل)",
        "Play the loaded macro with the settings above": "تشغيل الماكرو المحمّل بالإعدادات أعلاه",
        "Finish the current run, then stop": "إنهاء التشغيل الحالي ثم التوقف",
        "Abort immediately": "إلغاء فوري",
        "Ready": "جاهز",
        "Cancelling…": "جارٍ الإلغاء…",
        "Finishing run…": "جارٍ إنهاء التشغيل…",
        "Running": "قيد التشغيل",
        "Ready — press Run": "جاهز — اضغط تشغيل",
        "run {run}/{total}   ·   step {step}/{steps}": "تشغيل {run}/{total}   ·   خطوة {step}/{steps}",
        "{steps} steps   ·   {times} runs   ·   {speed} speed": "{steps} خطوة   ·   {times} تشغيل   ·   السرعة {speed}",
        "no macro loaded — press a macro hotkey": "لا يوجد ماكرو محمّل — اضغط اختصار ماكرو",

        # tray
        "    ...{count} more (see settings)": "    ...{count} إضافية (انظر الإعدادات)",
        "    no hotkeys configured": "    لا توجد اختصارات مكوّنة",
        "Next profile": "الملف الشخصي التالي",
        "Profiles": "الملفات الشخصية",
        "Show / hide macro controls": "إظهار / إخفاء أدوات الماكرو",
        "Hotkey settings...": "إعدادات Hotkey...",
        "Reload hotkeys": "إعادة تحميل الاختصارات",
        "Suspend all hotkeys": "تعليق جميع الاختصارات",
        "Open log": "فتح السجل",
        "Quit": "خروج",
        "Profile: {name}": "الملف الشخصي: {name}",
        "Reloaded: {count} hotkeys active": "تمت إعادة التحميل: {count} اختصار نشط",
        "No macro hotkey is configured": "لا يوجد اختصار ماكرو مكوّن",
        "Cannot save": "تعذر الحفظ",
        "Config problem": "مشكلة في الإعدادات",
        "Some hotkeys are unavailable": "بعض الاختصارات غير متاحة",
        "Macro": "ماكرو",
        "Starts with Windows": "يبدأ مع Windows",
        "Autostart disabled": "تم تعطيل البدء التلقائي",
        "{count} active": "{count} نشط",
        "paused": "متوقف مؤقتًا",
        "{count} hotkeys active": "{count} اختصار نشط",
        "{count} hotkeys active. Double-click the tray icon to edit them.":
            "{count} اختصار نشط. انقر نقرًا مزدوجًا على أيقونة شريط المهام لتعديلها.",
        "{name} is already used by another app":
            "{name} مستخدم بالفعل بواسطة تطبيق آخر",
        "Long-press/chords disabled": "تم تعطيل الضغط المطوّل / التشاركات",
        "Mouse hotkeys disabled": "تم تعطيل اختصارات الفأرة",
        "Leader key": "مفتاح البادئة",
        "Cannot open": "تعذر الفتح",
        "{name} failed": "فشل {name}",
        "paused - all hotkeys are free for other apps":
            "متوقف مؤقتًا - جميع الاختصارات متاحة للتطبيقات الأخرى",
        "resumed - {count} hotkeys active":
            "مستأنف - {count} اختصار نشط",
    },
}


def normalize(value: object) -> str:
    code = str(value or "en").strip().lower()
    return code if code in DISPLAY else "en"


def is_rtl(lang: object) -> bool:
    """True for languages whose interface flows right-to-left."""
    return normalize(lang) in RTL_LANGUAGES


def display(code: object) -> str:
    return DISPLAY[normalize(code)]


def code_from_display(value: object, default: str = "en") -> str:
    text = str(value or "").strip()
    for code, label in DISPLAY.items():
        if text.casefold() == label.casefold():
            return code
    return normalize(text or default)


def tr(text: str, lang: object = "en", **kwargs: object) -> str:
    out = TEXT.get(normalize(lang), {}).get(text, text)
    if kwargs and "{" in out:
        try:
            out = out.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return out
