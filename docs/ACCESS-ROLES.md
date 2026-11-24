# Delegating features to managers

As owner, open **Access Roles**, create or edit a role, and set its **View**, **Edit**, and **Delete** checkboxes. Assign that role in **Managers → Edit account → Account type**. Changes apply to the existing session; a new login is not needed. The server checks permissions on every request, including direct API calls and commands queued for Bluetooth execution.

View is required for Edit and Delete. Edit allows creation and changes; it does not imply Delete. Deletion uses its own grant even when a service exposes it as a POST action (SAS4 series deletion, VPN deletion, TTLock credential deletion and lock reset). Some features do not offer deletion operations; their Delete checkbox does not create a new operation.

Existing operational access is preserved. The new administrative permissions default to off, including FIB Bank recharge. A legacy visibility-only grant does not imply administrative Edit or Delete. Owners retain full server authorization; owner page visibility remains a navigation preference.

The role editor includes the existing operational sections, Settings, Software Updates and Access Roles, plus:

- FIB Bank recharge
- Managers and Inventory administration
- Card System, Device login, Towers API, Customer device access and Device API access
- TTLock and Deye configuration and sharing
- Payment setup and Client portal settings
- Customer Telegram bot, Telegram account lookup, Telegram notifications and WhatsApp notifications
- Backups and restore, VPN, PC and GPU updates, and SNMP visibility sharing

## FIB and FastPay

The owner configures the shared merchant accounts once. To allow a manager to recharge with FIB, grant **View + Edit** for **ISP Card** and **FIB Bank recharge**. The manager still needs SAS4 card permission and an available matching card. FastPay uses ISP Card permission and the configured shared FastPay merchant. See [PAYMENTS.md](PAYMENTS.md).

Payment setup is a separate, optional administrative grant. It is not required for checkout. A manager explicitly granted Payment setup Edit may configure the shared merchant account; revoking that permission makes a merchant selected under that manager unavailable for new payments. Existing payments retain their credential snapshot.

## Feature dependencies and account isolation

Navigation follows the selected permissions. Settings contains Backups, Payment gateways, Device API logins and VPN. My account contains Telegram notifications and the delegated customer integrations. SNMP visibility sharing is on the Managers page and requires Managers View. PC and GPU updates are inside Diagnostics, which also needs Settings View. Card System is inside ISP Card, so grant ISP Card View to reach it.

Device login profiles and customer integrations use the signed-in account's existing SAS4 connection. Grant ISP Card View (and Edit for customer changes) alongside those features. Towers API profiles can be managed independently; configuring tower API credentials requires Towers API Edit. Inventory administration enables privileged inventory actions within assigned places/towers, alongside the corresponding Towers or Network Map access. Device API access to tower credentials additionally requires Towers API Edit. Sharing a feature never signs the manager in as the owner or copies another account's integration credentials.

TTLock permissions apply to the signed-in account's TTLock connection. View can read locks and credentials, but cannot obtain the SDK lock data used to control hardware. Edit allows connecting, pairing, renaming and control; Delete allows disconnecting, credential removal and lock reset. Existing gateway/Bluetooth requirements still apply.

Deye configuration enables an account's own Deye connection. Existing read-only solar sharing remains available separately through **Deye Solar → Show solar readings**. Old inert Deye role bits do not become configuration grants.

## Delegated account and role administration

Managers can grant only View/Edit/Delete permissions they already hold. Delegated account administrators can create managers with explicit access roles, and manage other managers only within their own permission and inventory scope. They cannot create owner accounts, edit themselves, take over stronger accounts, or modify system account types. Owner accounts and the owner navigation recovery controls remain protected. SNMP visibility changes additionally require SNMP visibility sharing Edit.

Deletion and credential changes remain auditable under the actual acting account. Shared integrations recheck the configuring account's active status and required permissions; removing access does not silently select another configuration.
