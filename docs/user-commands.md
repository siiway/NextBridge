# User Commands

NextBridge supports several built-in commands that users can type directly into their chat platforms to manage their identity and cross-platform experience.

## Account Binding

By default, NextBridge tries to map mentions across platforms by matching **display names**. However, this can be unreliable if users have different names on different platforms. 

**Account Binding** allows you to explicitly link your IDs across platforms so that mentions always target the correct account.

### How to bind accounts

1.  **Generate a code**: On **Platform A** (e.g., Discord), type `/bind`.
    -   NextBridge will reply with a unique 6-digit code (e.g., `123456`).
2.  **Confirm the link**: On **Platform B** (e.g., QQ), type `/confirm 123456`.
3.  **Success**: Your Discord and QQ accounts are now linked!

Once linked, whenever someone mentions you on Discord, NextBridge will resolve your exact QQ User ID, triggering a native notification on the target platform.

### How to remove bindings

If you want to reset your identity or unlink your accounts, you can type:

-   `/rm`: Removes **all** links associated with your current global identity across all platforms.
-   `/rm <instance_id>`: Removes only the binding for a specific instance (e.g., `my_qq`).

### How to list bindings

To see all accounts currently linked to your identity, type:

`/list`
