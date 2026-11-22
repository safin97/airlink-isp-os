# Client recharge portal

Open `/client` on the same AirLink website. The standalone page contains customer sign-in, current service details, recharge by card PIN, and FIB Bank checkout. It has no staff navigation or manager-balance option. The local URL is http://127.0.0.1:18080/client.

After sign-in, customers see their username, first name, last name, phone number, service profile, recharge cost and expiry from SAS4. Missing values display as `—`. The initial cost is the customer service price; selecting FIB shows the selected SAS4 card value in IQD, and an existing payment shows its recorded amount.

The owner enables the portal in **My account → Client portal**, using their saved SAS4 connection and FIB merchant settings. Saving settings revokes existing customer sessions. Migration `b08de7149f25` adds separate settings and session tables; the local preview creates them automatically.

## Sign-in

On an ISP connection, AirLink can identify a customer by the source IP that reaches the server. Configure the actual subscriber ranges in **My account → Client portal → Automatic login IP ranges**. Enter a network in CIDR format, press **Add IP range**, and repeat for additional pools (up to 32). Remove a range using its remove button, then press **Save client portal** to apply the list. Existing saved ranges are preserved when adding another range. An empty list disables network auto-login. For example, `172.16.0.0/12` covers the private 172.16–172.31 space; `172.0.0.0/8` is accepted but includes public addresses and should only be used if it matches the actual subscriber allocation. Automatic login requires exactly one matching SAS4 online session, whose accounting update is at most two minutes old, and an enabled SAS4 customer. Ambiguous or stale sessions fall back to password login. Network sessions expire after 30 minutes and are checked against the IP and current accounting session on every request. Configure RADIUS interim accounting accordingly.

When automatic login cannot verify the connection, the sign-in page explains the reason and shows the source IP observed by AirLink when available. It distinguishes an IP outside the saved ranges, missing or ambiguous sessions, stale accounting and clock mismatches. Temporary automatic-login failures still allow the manual sign-in form to load. No customer identity, PIN or upstream error details are included in these diagnostics.

Automatic login uses RADIUS accounting and is independent of the subscriber router brand, including MikroTik and Ubiquiti. Browsers cannot extract stored PPPoE passwords from arbitrary routers. AirLink does not read or reveal device passwords.

From public internet/mobile connections, customers sign in through the SAS4 native customer portal API using their username and password. SAS4 normally uses the subscriber PPPoE credentials; if a separate customer-portal password is enabled in SAS4, that password applies. CAPTCHA is relayed when required. A separate HttpOnly cookie remembers manual sign-in for up to seven days, subject to native SAS4 token validity. No PPPoE password is saved; the native session token is encrypted. Manual sessions respect SAS4's `prm_ucp_activate` permission. Enabling IP auto-login authorizes card self-service for identified, enabled subscribers in those ranges.

## Network setup

The local Mac preview listens only on loopback; it is not publicly hosted. For customers to reach the page, run AirLink on a reachable server using the existing HTTPS Nginx deployment and route both ISP and public traffic to that server.

For auto-login, preserve each subscriber's actual PPPoE address all the way to the trusted web proxy. Shared NAT addresses cannot identify an individual account. Do not include NAT egress or proxy addresses in the subscriber ranges. Enable subscriber source-address validation on the ISP network.

The provided Nginx overwrites `X-Forwarded-For` with the connected peer, and Uvicorn trusts only the loopback Nginx proxy. The direct local preview disables proxy-header trust. An additional reverse proxy needs explicit trusted-source handling before auto-login will work; never trust arbitrary client-supplied IP headers.

## Recharge and payment

Customer APIs bind all operations to the authenticated subscriber; callers cannot select a different user, payment provider, or funding method. Staff and customer sessions are separate. PIN redemption uses the existing guarded SAS4 recharge operation.

Every click on **FIB Bank** on Home refreshes the SAS4 unused-PIN check. The page shows checking, available, or no-unused-PIN status, clears the previous quote before checking, and disables checkout when no eligible unused PIN is found or SAS4 is unavailable. FIB checkout rechecks the selected SAS4 Radius refill card for the customer's profile and charges its value in IQD. The PIN remains private and is submitted to SAS4 only after a verified production payment. Existing reservation, five-minute payment expiry, idempotency and owner-review safeguards apply. An unavailable card or unconfigured merchant prevents checkout. The payment worker continues after the customer closes the page.

Automated tests mock native customer authentication and FIB. A real subscriber sign-in, ISP routing/accounting match and production payment still need end-to-end validation on the deployed network.

## Signal, internet and speed checks

The signed-in portal uses a persistent phone-style bottom navigation bar: **Home**, **Usage**, **Packages**, **Support**, and **Profile**. Home contains service details, the speed gauge and recharge controls; Profile contains customer details and sign-out. Usage opens **My connection** for wireless signal, internet checks and speed tests. Switching tabs preserves the recharge form and pending payment. Leaving Usage stops its checks and monitoring refresh. Support introduces the portal without inventing provider contact information. Wireless signal is read from the existing customer monitoring service using the owner's configured SNMP/device credentials. AirLink matches both the subscriber ID and username, requires one unique IP/session in a current RADIUS snapshot, and returns only the signal, timestamp and status. It never returns device passwords or other customers' data. Missing, ambiguous or stale readings are shown as unavailable; signal readings older than 90 seconds are hidden. The panel refreshes every 30 seconds and has a manual refresh button. Device access must be enabled and the subscriber device reachable from AirLink.

**Check internet** makes a browser HTTPS request to Cloudflare's public test endpoint. A successful response proves that endpoint is reachable; a failure can also mean filtering or a test-server problem. This is separate from RADIUS online status.

**Start speed test** runs directly from the customer's browser to Cloudflare, showing estimated download/upload Mbps, median HTTP round-trip latency and HTTP timing jitter. It uses bounded adaptive transfers (at most 25.25 MB of payload), 12-second request timeouts, no account credentials, and a stop button. No test starts automatically and no results are saved. Tests measure the connection currently used by the browser; users on mobile data must connect to their home Wi-Fi to measure their home service. Single-request estimates include HTTP overhead and can understate high-capacity connections. The endpoint contract is documented in [Cloudflare's speed-test project](https://github.com/cloudflare/speedtest).

## Home shortcuts

Home offers **Our Cards**, **Recharge**, and **SpeedTest**. Our Cards syncs AirLink Basic, Plus, Pro, Ultra and Max from the saved SAS4 profile list. Each plan appears as a branded business card with the AirLink logo and the owner-specified catalog price: Basic 20,000, Plus 25,000, Pro 32,000, Ultra 40,000, and Max 50,000 IQD. Profiles not present in SAS4 are not invented. Refresh cards re-reads SAS4 names and stock while preserving these catalog prices. The catalog never retrieves PINs or creates payments. Recharge returns to the PIN/FIB form. Each card has Pay, which selects that package and checks recharge availability. A different package is applied only after verified FIB payment, as described below. Stock labels reflect series counts, with local reservations and actual PIN eligibility rechecked at checkout. SAS4 sometimes returns a blank used-card count for new series; this means the individual PIN must be checked, not that the series is sold out. PIN usage fields still determine whether a card can be purchased. FIB continues to charge the actual refill-card value, which can differ from the catalog price; the explicit checkout amount and payment step remain unchanged.

The Home **SpeedTest** shortcut reveals and starts the in-app speed gauge. Its measurements come from the browser connection to Cloudflare; they are not Speedtest.net results. The connection test is also available under Usage.

## Package payments

Every card in **Packages** has **Pay**. Selecting a card opens FIB checkout for that package, checks fresh unused SAS4 PIN stock, and shows the actual card value before payment. The existing service profile remains unchanged until a production FIB payment is verified. AirLink then changes the customer’s SAS4 profile and redeems the reserved PIN once. Sandbox payments do not change service.

Only the five AirLink catalog plans are eligible. SAS4 must permit changing that customer’s profile, including active-user profile changes when applicable. Unavailable stock or permissions block checkout. An existing unresolved payment must finish before buying another package. Uncertain profile changes or activation failures remain held for provider review; they are never automatically replayed.
