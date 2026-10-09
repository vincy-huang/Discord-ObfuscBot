# **Discord ObfuscBot**
## Condition Masking Interface

This is a Discord chatbot tool designed to create a space for hosting experimental chats between a human participant pair or between a human participant and an chatbot. This tool is made to make the experimental conditions blind to the research experimenter as much as possible within the constraints of the Discord environment through tinkering arround the various permissions on Discord. By serving as the sole intermediary between the researcher and the participants, this tool eliminates experimenter bias during live data collection and interaction.

## Set Up the Study Discord Server: Roles, Categories, and Channels
### Installation & Discord Server Set Up
1. [Download Discord]
1. [Create a server]
1. [Discord Developer Portal]
   * Bot permission specifications & get the app link
1. [Allow Discord Developer Mode]
### Create Discord Roles
Create:
   * Staff
   * RA
   * Condition-1
   * Condition-2
        > Note: The study supervisors may want to hide what `Condition-1` and `Condition-1` really are!
### Create Discord Categories:
Create:
   * Staffs
   * Sessions
  
### Create Discord Channels:
* Create a day in advance for each new experiment session, for example:
   * `s01` for session 01
   * `s-pi01` for pilot 01


## Installation
1. Download this repo's latest release onto your local machine. The newly saved folder should have the same name as this repo `Discord-ObfuscBot`.
1. Open your machine's Terminal application at the saved `Discord-ObfuscBot` folder.
1. [***Requirements***]
    * [Python & package requirements] for running the bot 
        > (This is the minimal requirement for running the bot locally)
        > - Python 3.14.7
        > - discord.py>=2.4
        > - python-dotenv>=1.0
        > - openai>=1.40
        
        > - fastapi>=0.115
        > - uvicorn>=0.30
        > - pymongo>=4.8
        > - python-dotenv>=1.0

    * [Render] for backend
    * [MongoDB Atlas] for cloud database
        > Randomized participant condition sheet & session data exports storage
        
## How to Run the Bot during the Study
1. Before running the study, ensure that a separate research assistant (RA) has done relaying the conditions for the randomized participants for the current study session (see How to Relay the Conditions section).
1. [***Open Discord***, leave it open]
1. [***Activate environment for python scripts***]
1. Copy and paste the following command into your Terminal and press **Enter** on your keyboard: 
    > ```python bot.py```
1. Wait until the "Relay awakened. You may run /start in Discord." message pops up in the Terminal interface:
   <img src="images/initiate-bot.png" width="600">

## How to Test the Bot on One Machine
> [**Work in progress**]


> ***🚧 Instruction still in progress 🚧 ***


## Reference
Signh, A. (2024). *UBC-Discord-Bot*. GitHub. https://github.com/wwbp/UBC-Discord-Bot/

Miras, P. (2026). *chatbot-backend*. GitHub. https://github.co (Private repository).


## License
[![CC BY-NC 4.0][cc-by-nc-shield]][cc-by-nc]

The codebase is licensed under a
[Creative Commons Attribution-NonCommercial 4.0 International License][cc-by-nc].

[![CC BY-NC 4.0][cc-by-nc-image]][cc-by-nc]

[cc-by-nc]: https://creativecommons.org/licenses/by-nc/4.0/
[cc-by-nc-image]: https://licensebuttons.net/l/by-nc/4.0/88x31.png
[cc-by-nc-shield]: https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg
