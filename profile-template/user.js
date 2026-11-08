/* Dedicated Figma desktop window. */
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
user_pref("browser.tabs.inTitlebar", 1);
user_pref("browser.tabs.vertical", false);
user_pref("sidebar.verticalTabs", false);
user_pref("sidebar.revamp", false);
user_pref("sidebar.visibility", "hide-sidebar");
user_pref("browser.uidensity", 1);
user_pref("browser.startup.homepage", "https://www.figma.com/");
user_pref("browser.startup.page", 3);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.newtabpage.enabled", false);
user_pref("browser.tabs.closeWindowWithLastTab", true);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.toolbars.bookmarks.visibility", "never");
user_pref("browser.theme.content-theme", 0);
user_pref("browser.theme.toolbar-theme", 0);
user_pref("ui.systemUsesDarkTheme", 1);
user_pref("browser.sessionstore.resume_from_crash", true);
user_pref("dom.event.clipboardevents.enabled", true);
user_pref("dom.allow_cut_copy", true);
user_pref("ui.key.menuAccessKeyFocuses", false);
user_pref("ui.key.menuAccessKey", 0);
/* Disable wheel-click paste in the dedicated Figma profile. */
user_pref("middlemouse.paste", false);

/* Finer Figma canvas zoom for Ctrl+wheel and native touchpad pinch.
 * Firefox forwards both as Control-modified wheel events. */
user_pref("mousewheel.with_control.delta_multiplier_y", 50);

/* Keep exported and downloaded PDFs outside the Figma workspace. */
user_pref("pdfjs.disabled", true);
user_pref("browser.download.open_pdf_attachments_inline", false);

/* No telemetry is required by the standalone workspace. */
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.enabled", false);
