# Building the mssql-dxt.dxt Extension File

This guide provides step-by-step instructions on how to build the `mssql-dxt.dxt` extension file from the source code.

## Prerequisites

Before you begin, ensure you have the following software installed on your system:

*   **Git:** For cloning the repository. You can download it from [git-scm.com](https://git-scm.com/).
*   **Node.js and npm:** Node.js is a JavaScript runtime, and npm is its package manager. DXT CLI is distributed via npm. You can download them from [nodejs.org](https://nodejs.org/).
*   **Python:** The server-side logic of the extension is written in Python. Ensure you have Python 3.x installed. You can download it from [python.org](https://www.python.org/downloads/).
*   **DXT CLI:** The command-line interface for developing and packaging Claude Desktop extensions. You can install it globally using npm by running:
    ```bash
    npm install -g @claude-desktop/dxt-cli
    ```

## Building the Extension

Follow these steps to build the `mssql-dxt.dxt` file:

1.  **Clone the Repository:**
    Open your terminal or command prompt and navigate to the directory where you want to clone the repository. Then, run the following command:
    ```bash
    git clone <repository_url>
    cd <repository_name> # e.g., cd mssql-dxt-repository
    ```
    Replace `<repository_url>` with the actual URL of the Git repository and `<repository_name>` with the name of the cloned directory.

2.  **Install Python Dependencies:**
    The Python server for this extension may have dependencies listed in a `requirements.txt` file (usually located in the `server` directory or a similar path). These dependencies need to be installed into a specific folder within the extension's `server` directory, typically `server/lib`.

    Navigate to the extension's root directory (e.g., `mssql-dxt-repository`) in your terminal and run:
    ```bash
    # Assuming requirements.txt is in the 'server' directory
    # and you want to install dependencies into 'server/lib'
    pip install -r server/requirements.txt -t server/lib
    ```
    If your `requirements.txt` is located elsewhere, or if the target directory for libraries is different (check the extension's `manifest.json` or specific project structure), adjust the paths accordingly. Ensure the `server/lib` directory exists or is created by this command. If `pip` installs packages to a user-specific site-packages directory by default, you might need to ensure it targets the `server/lib` directory correctly, possibly by activating a virtual environment or using more specific `pip` options if `-t` is not sufficient for your setup.

3.  **Package the Extension:**
    Once the dependencies are correctly placed, you can package the extension using the DXT CLI. In the root directory of the extension, run:
    ```bash
    dxt pack
    ```
    This command will compile the extension and create a `.dxt` file.

## Locating the .dxt File

After the `dxt pack` command successfully completes, the generated `.dxt` file will typically be found in the root directory of the cloned repository, or sometimes in a `dist` or build-specific folder, depending on the project's configuration. The file will be named something like `mssql-dxt.dxt` or `<extension-name>.dxt`.

## Installing the Extension in Claude Desktop

Once you have the `.dxt` file, you can install it in Claude Desktop:

1.  Open Claude Desktop.
2.  Navigate to the Extensions view. This is typically accessible via a puzzle piece icon in the sidebar or through a menu option like `View > Extensions` or `File > Preferences > Extensions`.
3.  Look for an option to install an extension from a file. This might be an "Install from VSIX/DXT..." button (often found under a "..." menu in the Extensions panel) or a similar wording.
4.  Select the `.dxt` file you built (e.g., `mssql-dxt.dxt`) through the file dialog.
5.  Claude Desktop will install the extension. You may need to reload or restart Claude Desktop for the extension to become active.

Please refer to the official Claude Desktop documentation for the most up-to-date instructions on installing extensions, as UI elements and procedures can change with new versions.
