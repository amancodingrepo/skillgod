# SkillGod install redirect
# irm skillgod.dev/install.ps1 | iex
$url = "https://raw.githubusercontent.com/amancodingrepo/skillgod/main/scripts/install.ps1"
Invoke-Expression (Invoke-WebRequest -Uri $url -UseBasicParsing).Content
