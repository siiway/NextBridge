> This document was written by AI and has been manually reviewed.

# User Commands

NextBridge supports several built-in commands that users can type directly into their chat platforms to manage their identity and cross-platform experience.

## Account Binding

NextBridge resolves cross-platform mentions by trying **explicit binding (bind)** first. If no binding is available, it may fall back to matching **display names** on the target platform.

**Built-in commands use the global command prefix from config. The default prefix is `nb`, so the examples below use `/nb ...`.**

Type `/nb` (or `/nb help`) to see the list of available built-in commands.

**Account Binding** allows you to explicitly link your IDs across platforms so that mentions always target the correct account.

### How to bind accounts

1.  **Generate a code**: On **Platform A** (e.g., Discord), type `/nb bind setup`.
    -   NextBridge will reply with a unique 6-digit code (e.g., `123456`).
2.  **Confirm the link**: On **Platform B** (e.g., QQ), type `/nb bind confirm 123456`.
3.  **Success**: Your Discord and QQ accounts are now linked!

Once linked, whenever someone mentions you on Discord, NextBridge will resolve your exact QQ User ID, triggering a native notification on the target platform.

### How to remove bindings

If you want to reset your identity or unlink your accounts, you can type:

-   `/nb bind rm`: Removes **all** links associated with your current global identity across all platforms.
-   `/nb bind rm <instance_id>`: Removes only the binding for a specific instance (e.g., `my_qq`).

### How to list bindings

To see all accounts currently linked to your identity, type:

`/nb bind list`

## Cross-Platform Ping by Target

When someone does not have an account on your current platform, you can ping them by a target identifier on another platform.

Use:

`/ping <target>`

Example:

- You are on QQ.
- The target user only has a Discord account named `Alice`.
- Send `/ping Alice` in QQ.

NextBridge will try to resolve the target on each destination instance and convert it into a native mention where possible.

Default target resolution (non-QQ):
- Prefer explicit account bindings if available.
- Otherwise resolve by the target platform username cache (instead of nickname).

QQ target resolution:
- Prefer explicit account bindings if available.
- If the target text is numeric, it is treated as a QQ number directly.
- Otherwise, it is treated as a QQ qid alias and resolved from cached user mappings.
