/**
 * learn-topics.ts: Static topic definitions for the /learn/ education hub (E-38).
 *
 * Three topic types:
 *   exploit: 10 DeFi exploit classes, anchored to real hacks categories
 *   factor: 20 ★ critical factors from the rubric taxonomy
 *   chain: 10 chains in the v1 coverage universe
 *
 * Each topic has a narrative intro (plain English for non-technical readers)
 * and structured metadata used to fetch related hacks/factors from the DB.
 */

export type TopicType = 'exploit' | 'factor' | 'chain';

export interface LearnTopic {
  type: TopicType;
  slug: string;
  title: string;
  description: string;
  /** Plain-language body (1-3 paragraphs). No HTML; rendered as <p> tags. */
  body: string[];
  /** For exploit topics: the hack category string to filter hacks by. */
  hackCategory?: string;
  /** For factor topics: the RD-F-NNN factor ID. */
  factorId?: string;
  /** For chain topics: the chain name used in hacks.chain. */
  chainName?: string;
  /** Related factor IDs to show as contextual links. */
  relatedFactors?: string[];
}

// ── Exploit class topics (10) ────────────────────────────────────────────────

const EXPLOITS: LearnTopic[] = [
  {
    type: 'exploit',
    slug: 'flash-loan-attack',
    title: 'Flash Loan Attacks',
    description: 'How attackers use uncollateralized single-transaction loans to manipulate DeFi protocols and drain funds.',
    hackCategory: 'Flash loan attack',
    relatedFactors: ['RD-F-053', 'RD-F-070'],
    body: [
      'Flash loans allow anyone to borrow unlimited funds within a single Ethereum transaction, with no collateral required as long as the loan is repaid before the block ends. This mechanic is legitimate when used for arbitrage or liquidation bots, but it becomes an attack vector when a protocol prices assets using spot DEX pools that can be manipulated within the same transaction.',
      'A classic flash loan attack proceeds in four steps: borrow a large sum, use it to skew the price of an asset on a DEX, exploit the manipulated price on the target protocol (e.g., take out an under-collateralized loan or trigger a favourable liquidation), then repay the flash loan, all within one atomic transaction. The profit is kept; the price reverts after the block.',
      'The primary mitigation is price oracle hardening (see RD-F-053): use time-weighted average prices (TWAPs), Chainlink feeds, or multi-source medianized prices rather than spot pool prices. DeFi Risk grades protocols on oracle robustness as a ★ critical factor precisely because spot-pool oracles enable the largest class of flash-loan exploits.',
    ],
  },
  {
    type: 'exploit',
    slug: 'reentrancy',
    title: 'Reentrancy Attacks',
    description: 'How recursive external calls allow attackers to drain funds before balance updates are written.',
    hackCategory: 'Reentrancy',
    relatedFactors: ['RD-F-001', 'RD-F-022'],
    body: [
      'Reentrancy is one of the oldest smart contract vulnerabilities and remains active today. When a contract sends ETH or makes an external call before updating its own state, a malicious receiver contract can call back into the original function repeatedly before the first invocation has finished. Each recursive call sees the pre-update state and can withdraw funds that have already been "sent".',
      'The DAO hack in 2016 ($60M equivalent) is the canonical example, but reentrancy appears in more subtle forms: cross-function reentrancy (re-entering a different function that shares state), cross-contract reentrancy (re-entering via an intermediary), and read-only reentrancy (manipulating view functions during execution). Modern audits check for all variants.',
      'Mitigations include the checks-effects-interactions pattern (update state before external calls), reentrancy guards, and avoiding ETH transfers to untrusted addresses in state-sensitive contexts. DeFi Risk assesses whether protocols have been audited against reentrancy patterns and whether audit scope matches deployed code (RD-F-001).',
    ],
  },
  {
    type: 'exploit',
    slug: 'oracle-manipulation',
    title: 'Oracle Manipulation',
    description: 'How attackers exploit weak price feeds to skew on-chain valuations and extract value from lending and derivative protocols.',
    hackCategory: 'Oracle manipulation',
    relatedFactors: ['RD-F-053', 'RD-F-180'],
    body: [
      'Oracles bring external price information on-chain. When an oracle can be manipulated, either by flash loan, large-capital market impact, or stale feed, every protocol that trusts it becomes vulnerable. The largest single class of DeFi exploits by dollar value traces back to oracle manipulation.',
      'Spot DEX pools (Uniswap v2/v3, Curve) are the most common manipulable source: their prices reflect instantaneous supply and demand, which can be shifted dramatically within a block using a flash loan. Protocols that read price directly from pool reserves without a TWAP or secondary reference can be exploited by anyone with enough capital for one transaction.',
      'DeFi Risk marks "oracle source = spot DEX pool with no TWAP or fallback" (RD-F-053) and "immutable oracle address with no admin-replaceable wrapper" (RD-F-180) as ★ critical factors. These two factors together cover the largest observable cluster of oracle exploits in the historical database.',
    ],
  },
  {
    type: 'exploit',
    slug: 'access-control',
    title: 'Access Control Failures',
    description: 'How missing or bypassed permission checks allow unauthorized actors to call privileged functions.',
    hackCategory: 'Access control',
    relatedFactors: ['RD-F-022', 'RD-F-027', 'RD-F-046'],
    body: [
      'Access control vulnerabilities occur when privileged functions, including minting, withdrawing, upgrading, or configuring the protocol, can be called by addresses that should not have that capability. This happens through missing modifiers, incorrect role assignments, public initializers, or proxy implementation contracts that accept admin calls without checking the caller.',
      'The "public initialize" pattern (RD-F-022) is particularly dangerous: if an implementation contract exposes initialize() without an initializer modifier, anyone can call it after deployment and claim admin rights. This is a one-transaction exploit: no flash loan, no market manipulation required. It was used to drain several protocols in 2022–2023.',
      'DeFi Risk also grades the admin key structure itself: a single EOA with upgrade/rescue authority (RD-F-027) is a critical risk even when the access control code is correct, because the key can be stolen, coerced, or used maliciously without any contract-level exploit.',
    ],
  },
  {
    type: 'exploit',
    slug: 'logic-error',
    title: 'Logic Errors',
    description: 'How incorrect business logic, including rounding, state transitions, or arithmetic mistakes, creates exploitable discrepancies.',
    hackCategory: 'Logic error',
    relatedFactors: ['RD-F-001', 'RD-F-139'],
    body: [
      'Logic errors are flaws in the intended behaviour of a contract, distinct from reentrancy or access control violations. Common manifestations include precision loss in integer division (allowing users to round up rewards or round down repayments in their favour), incorrect fee accounting, flawed liquidation formulas, or edge cases in state machines that leave funds permanently locked or extractable.',
      'These vulnerabilities are especially pernicious because they often pass formal audits; the code does exactly what it says, but the specification was wrong. They are most commonly discovered by adversarial fuzzers, economic modelling, or in production when an alert user notices anomalous returns.',
      'DeFi Risk flags logic-error exposure through audit scope mismatch (RD-F-001) and post-audit code changes without re-audit (RD-F-139): the highest-risk window for logic errors is when production code diverges from the audited version, even by one line.',
    ],
  },
  {
    type: 'exploit',
    slug: 'economic-design',
    title: 'Economic Design Failures',
    description: 'How game-theoretic weaknesses in tokenomics, incentive structures, or collateral design enable death spirals and value extraction.',
    hackCategory: 'Economic design',
    relatedFactors: ['RD-F-070', 'RD-F-053'],
    body: [
      'Economic design failures differ from code bugs: the contracts execute exactly as written, but the incentive structure creates conditions where rational actors can extract value at others\' expense, or where cascading failures become unavoidable. Classic examples include undercollateralized stablecoins, death-spiral tokenomics, and empty-market exploitation in lending protocols.',
      'The empty cToken market exploit (RD-F-070) is a documented critical pattern: in Compound V2 forks, when the first depositor into a new market contributes a tiny amount, they can manipulate the exchange rate and drain subsequent depositors. Nine separate protocols have been exploited via this single pattern.',
      'Economic risk factors in DeFi Risk (Category 4) assess collateral parameters, liquidation incentive design, TVL concentration, and susceptibility to flash-loan-amplified economic attacks. The grade reflects structural robustness of the economic model, not current market conditions.',
    ],
  },
  {
    type: 'exploit',
    slug: 'bridge-exploit',
    title: 'Bridge Exploits',
    description: 'How cross-chain bridge vulnerabilities allow attackers to mint unbacked assets or drain bridge custodians.',
    hackCategory: 'Bridge exploit',
    relatedFactors: ['RD-F-151', 'RD-F-154'],
    body: [
      'Cross-chain bridges hold some of the largest concentrations of value in DeFi and have been the single most targeted category by high-value attackers. Bridges rely on off-chain validators or on-chain proof systems to attest that an asset was locked on chain A before minting it on chain B. Any flaw in this attestation mechanism allows minting without locking, effectively creating unlimited counterfeit assets.',
      'The Ronin ($625M), Wormhole ($320M), and Nomad ($190M) exploits each exploited different bridge vulnerabilities: stolen private keys, a missing ecrecover return-value check (RD-F-151), and an initialization bug that made any message with a zero root valid (RD-F-154) respectively.',
      'DeFi Risk marks both Wormhole-class (RD-F-151) and Nomad-class (RD-F-154) vulnerabilities as ★ critical factors in the Cross-chain category. Protocols with bridge surface exposure undergo the full Category 10 assessment; non-bridge-touching protocols have Cat 10 marked N/A.',
    ],
  },
  {
    type: 'exploit',
    slug: 'private-key-compromise',
    title: 'Private Key Compromise',
    description: 'How stolen, leaked, or maliciously used admin keys bypass all on-chain security and directly drain protocol funds.',
    hackCategory: 'Private key compromise',
    relatedFactors: ['RD-F-027', 'RD-F-043', 'RD-F-124', 'RD-F-125'],
    body: [
      'Private key compromise is the simplest exploit vector: if an attacker gains control of a deployer or admin wallet, they bypass every on-chain security measure and can directly call privileged functions. This happens through phishing, malware, supply-chain attacks on developer tooling, insider threats, and, in state-sponsored cases, sophisticated social engineering.',
      'The structural risk is determined by how much power a single key holds. A protocol where a single EOA can upgrade the implementation, mint tokens without limit, or withdraw the treasury with no timelock can be drained in one transaction if that key is compromised. The DPRK Lazarus Group has consistently targeted protocols with this architecture.',
      'DeFi Risk grades key management risk through several ★ critical factors: single admin EOA (RD-F-027), deployer wallet mixer-funded within 30 days (RD-F-124), and deployer linked within 3 hops to DPRK/Lazarus clusters (RD-F-125). One critical red blocks A and adds 5 risk points; two or more force D or worse, and three or more force F.',
    ],
  },
  {
    type: 'exploit',
    slug: 'governance-attack',
    title: 'Governance Attacks',
    description: 'How attackers acquire or borrow voting power to pass malicious proposals that drain treasuries or take control of protocol admin.',
    hackCategory: 'Governance attack',
    relatedFactors: ['RD-F-036', 'RD-F-039', 'RD-F-041'],
    body: [
      'Governance attacks exploit the on-chain voting systems that DeFi protocols use for decision-making. If a governance token can be flash-loaned, bought cheaply, or if voting weight is not snapshotted before proposal creation, an attacker can temporarily acquire a majority stake, pass a malicious proposal, execute it, and return the borrowed tokens, all before legitimate holders can react.',
      'The Beanstalk ($182M) exploit is the canonical governance attack: the attacker used a flash loan to acquire a temporary supermajority, immediately executed an emergency proposal to drain the protocol, repaid the loan, and walked away. The entire attack took one transaction. The vulnerability was that voting weight was not snapshotted at proposal creation time (RD-F-036).',
      'DeFi Risk grades governance attack surface through ★ critical factors including flash-loanable voting weight (RD-F-036), delegatecall in proposal execution without a target allowlist (RD-F-039), and rescue/emergencyWithdraw without timelock (RD-F-041). Protocols with mature timelock-enforced governance score better across all three.',
    ],
  },
  {
    type: 'exploit',
    slug: 'rugpull',
    title: 'Rug Pulls & Exit Scams',
    description: 'How malicious deployers design protocols to allow controlled fund extraction, then drain them at a chosen moment.',
    hackCategory: 'Rug pull',
    relatedFactors: ['RD-F-042', 'RD-F-043', 'RD-F-124', 'RD-F-125'],
    body: [
      'A rug pull is a deliberate exit scam: the team designs the protocol to retain a hidden extraction capability, attracts users and liquidity, then exercises that capability to drain funds. Common mechanisms include unlimited mint functions, backdoor admin functions that bypass timelocks, or liquidity pool designs where the team holds most LP tokens and can remove them without restriction.',
      'Rug pulls are distinguished from hacks by intent: the code executes as designed, but the design was malicious from the start. They are the hardest category to grade from code alone; a team can write impeccable Solidity while retaining a privileged mint function (RD-F-042) that only needs to be called once.',
      'DeFi Risk addresses rug pull risk through deployer identity factors (mixer-funded wallets at RD-F-124, DPRK-linked at RD-F-125) and structural capability factors (unlimited mint at RD-F-042, admin = deployer EOA after 7 days at RD-F-043). The combination of anomalous deployer signals and retained extraction capability is the strongest observable rug precursor.',
    ],
  },
];

// ── Critical factor topics (20) ──────────────────────────────────────────────

const FACTORS: LearnTopic[] = [
  {
    type: 'factor',
    slug: 'RD-F-027',
    title: 'Single Admin EOA | Why It Matters',
    description: 'Understanding why a single externally-owned account with admin power is a critical DeFi risk factor.',
    factorId: 'RD-F-027',
    body: [
      'When a protocol\'s most powerful role, such as upgrade authority, treasury access, or emergency withdraw, is held by a single externally-owned account (EOA, i.e., a plain wallet rather than a multisig), the entire protocol\'s security reduces to the security of that one private key. One phishing email, one malware infection, or one insider threat is sufficient for a complete protocol drain.',
      'Multisigs require M-of-N co-signers, making theft dramatically harder. Timelocks add a window during which the community can detect and respond to a malicious action. Neither defence is present with a single EOA admin. The historical evidence is clear: most rug pulls and insider-threat exploits used single-EOA control.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-028',
    title: 'Low-Threshold Multisig vs TVL',
    description: 'Why a 2/3 multisig on a $500M protocol is structurally different from the same setup on a $1M protocol.',
    factorId: 'RD-F-028',
    body: [
      'A multisig is only as secure as its threshold requires. A 2/3 multisig means any two of three signers can authorize any action, including draining the treasury. At $10M TVL this may be acceptable risk-adjusted security. At $500M TVL it represents a $250M bounty to any adversary who can compromise or coerce two specific individuals.',
      'DeFi Risk evaluates multisig threshold relative to TVL peer cohort: a 2/3 multisig where 5/8 is the norm among comparable protocols is a structural anomaly. The anomaly becomes a ★ critical red when TVL exceeds $100M, because at that scale the "low threshold" directly enables nation-state-level attacks.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-041',
    title: 'Emergency Withdraw Without Timelock',
    description: 'Why rescue/emergencyWithdraw functions that bypass timelocks are a ★ critical risk.',
    factorId: 'RD-F-041',
    body: [
      'Emergency withdraw or rescue functions exist to recover funds in crises. When they bypass the protocol\'s normal governance timelock, they create an immediate extraction capability: a compromised admin key can drain all user funds in a single transaction with no community warning period.',
      'The absence of a timelock on emergency functions is classified as ★ critical because it eliminates the only protection against fast-moving insider threats and compromised keys. A 48-hour timelock on emergency withdrawals gives users time to react; without it, the attack window is measured in seconds.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-042',
    title: 'Unlimited Admin Mint',
    description: 'Why an admin mint function with no supply cap or multisig requirement is a ★ critical risk factor.',
    factorId: 'RD-F-042',
    body: [
      'A mint function callable by a single admin address with no cap enables inflation-based extraction: the admin mints new tokens, immediately sells them against protocol liquidity, and exits. For protocols whose token is the collateral, this is equivalent to a direct treasury drain.',
      'This pattern appears in many rug pulls. The code is often presented as a "guardian function for emergencies" or "liquidity bootstrapping mechanism." The risk is identical regardless of stated intent: the capability exists, and capability is what the rubric grades.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-043',
    title: 'Admin = Deployer After 7 Days',
    description: 'Why a protocol where the deployer still holds admin rights after 7 days is a structural red flag.',
    factorId: 'RD-F-043',
    body: [
      'At launch, it is normal for the deploying team to retain admin keys; multisig setup, initial configuration, and deployment verification take time. After 7 days, any legitimate protocol should have transferred administrative control to a community multisig or DAO. Protocols that retain deployer-EOA admin control beyond this window are either intentionally backdoored or operationally negligent.',
      'This factor is strongly correlated with rug pulls in the historical database: most protocols where the deployer drained funds had never transferred admin authority to a multisig. The 7-day threshold is conservative; legitimate protocols typically complete this transfer within 24-72 hours.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-046',
    title: 'Unverified Contract at Launch',
    description: 'Why deploying unverified contracts, with no public ABI or Etherscan source, is a ★ critical risk signal.',
    factorId: 'RD-F-046',
    body: [
      'Source code verification on Etherscan (or equivalent block explorer) makes a contract\'s logic publicly auditable. Unverified contracts are opaque: users must trust the team\'s claims about what the code does, with no ability to verify. An unverified contract with live TVL is the simplest possible rug precursor; the team can execute any function, including hidden extraction functions, without external parties knowing they exist.',
      'This factor grades as ★ critical because unverified code with live TVL removes the most basic accountability mechanism DeFi relies on. Even security researchers cannot audit what they cannot read. The floor is clear: if the code is not verified, no meaningful structural assessment is possible.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-036',
    title: 'Flash-Loanable Voting Weight',
    description: 'Why governance tokens that can be flash-loaned enable Beanstalk-style attacks.',
    factorId: 'RD-F-036',
    body: [
      'When a governance token can be borrowed via flash loan and used to vote within the same transaction, a temporary supermajority can be obtained cheaply. The Beanstalk exploit ($182M) demonstrated this: the attacker flash-loaned enough governance tokens to pass an emergency proposal immediately, drain the treasury, and repay the loan, all in one block.',
      'The mitigation is snapshotting voting weight at proposal creation time rather than at execution time. Compound, Aave, and most mature governance systems do this. Protocols that allow freshly acquired tokens to vote immediately on live proposals remain vulnerable to this exact attack pattern.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-039',
    title: 'Delegatecall in Proposals Without Allowlist',
    description: 'Why allowing delegatecall to arbitrary addresses in governance execution is a full-drain vulnerability.',
    factorId: 'RD-F-039',
    body: [
      'Governance proposals that use delegatecall to an arbitrary target address give that proposal the full context and permissions of the Governor contract. A malicious proposal can delegatecall to an attacker-controlled contract that drains the treasury, upgrades the implementation to a backdoored version, or mints tokens without limit.',
      'The mitigation is an allowlist of approved target contracts for delegatecall in proposals. Without this allowlist, any passing proposal, whether obtained through legitimate majority or governance attack, can execute arbitrary code with the protocol\'s full permissions.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-022',
    title: 'Public Initialize Without Guard',
    description: 'Why an unprotected initialize() function on an implementation contract enables immediate ownership takeover.',
    factorId: 'RD-F-022',
    body: [
      'Proxy contracts separate storage (proxy) from logic (implementation). The implementation contract must be initialized to set its owner, but if that initialization is not locked, anyone can call initialize() on the bare implementation and claim its admin rights. From there, they can often exploit the proxy storage via delegatecall.',
      'OpenZeppelin\'s _disableInitializers() in the constructor is the standard fix. This ★ critical factor has been the root cause in multiple protocol drains where a publicly accessible implementation contract was taken over without touching the proxy at all.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-001',
    title: 'Audit Scope Mismatch',
    description: 'Why "audited protocol" is only meaningful if the deployed bytecode matches the audited commit.',
    factorId: 'RD-F-001',
    body: [
      'An audit\'s value is bounded by what it covered. If the code deployed on-chain differs from the commit hash cited in the audit report, the audit provides no security guarantee for the deployment. This mismatch is the single most common ★ critical factor in the historical exploit database, appearing as a contributing factor in approximately 25 separate protocol incidents.',
      'Bytecode verification is straightforward: compare the Etherscan-verified source against the commit hash in the audit report. Any divergence, even a one-line change, removes the audit\'s coverage of affected functions. The Euler Finance exploit is a documented case where a post-audit change introduced the vulnerability that enabled the $197M loss.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-143',
    title: 'Reinitializable Implementation',
    description: 'Why a proxy implementation that can be re-initialized enables a takeover attack.',
    factorId: 'RD-F-143',
    body: [
      'If an implementation contract can be initialized more than once, an attacker who calls initialize() a second time can overwrite the stored owner/admin address and take control. This is the complement of RD-F-022: that factor covers the initial takeover of an uninitialized implementation; this covers the re-initialization of an already-configured one.',
      'OpenZeppelin\'s _disableInitializers() prevents re-initialization by permanently locking the initializer after the first call. Implementations that use custom initialization without this guard, or that use initializer modifiers incorrectly, remain vulnerable to this proxy-takeover pattern.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-139',
    title: 'Post-Audit Code Changes Without Re-Audit',
    description: 'Why code changes deployed after the audit closes the audit\'s security guarantees for those files.',
    factorId: 'RD-F-139',
    body: [
      'An audit covers the code at a specific commit. When production code is updated after the audit concludes, even for "minor" fixes or gas optimisations, those changes are unaudited. If the changes affect security-sensitive logic (access control, arithmetic, state transitions), the protocol has live unaudited code.',
      'The Euler Finance exploit ($197M) is the canonical case: a donation-related code change was added after the last audit and was never reviewed. That change introduced the vulnerability. Post-audit changes without re-audit coverage are ★ critical precisely because they represent the most common path from audited-safe to production-vulnerable.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-070',
    title: 'Empty cToken-Style Market',
    description: 'How the first-depositor manipulation of Compound V2 forks enables a documented 9-protocol exploit pattern.',
    factorId: 'RD-F-070',
    body: [
      'In Compound V2 forks, the exchange rate between cTokens and underlying assets is calculated as totalCash / totalSupply. When totalSupply is 0 (empty market) and the first depositor sends a tiny amount, they receive 1 cToken and set the exchange rate arbitrarily. A subsequent large donation (which increases totalCash without changing totalSupply) inflates the exchange rate so dramatically that rounding errors in subsequent deposits cause complete loss for those depositors.',
      'This specific pattern has been documented in at least 9 separate protocol exploits. The mitigation is virtual offsets (a non-zero initial supply to prevent the empty-market state) and a minimum deposit requirement. Any Compound V2 fork without these mitigations in place is critically vulnerable to this one-transaction exploit.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-053',
    title: 'Spot DEX Pool Oracle',
    description: 'Why using a spot DEX price (no TWAP, no fallback) as an oracle is the largest single DeFi exploit class.',
    factorId: 'RD-F-053',
    body: [
      'Spot DEX prices reflect instantaneous market state: they can be moved within a single block by any party with sufficient capital (via flash loan). When a lending or derivative protocol uses a spot pool price as its price source, it trusts a number that can be manipulated by anyone, transaction-by-transaction, without any sustained market position.',
      'Time-weighted average prices (TWAPs) and external oracle networks (Chainlink, Pyth) are resistant to single-transaction manipulation because they aggregate price over multiple blocks. DeFi Risk marks spot-pool-only oracle usage as ★ critical because it has been the exploited mechanism in more documented incidents than any other single factor in the database.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-124',
    title: 'Deployer Wallet Mixer-Funded',
    description: 'Why a deployment wallet funded through Tornado Cash within 30 days is a documented rug precursor.',
    factorId: 'RD-F-124',
    body: [
      'Mixer services like Tornado Cash break the on-chain link between funding source and recipient wallet. Legitimate teams have no reason to obscure their funding source; on-chain transparency is the norm in DeFi, and professional teams typically use well-documented wallets. Deployer wallets funded through mixers immediately before launch are strongly associated with intent to preserve anonymity for post-exploit exit.',
      'The 30-day window is derived from empirical analysis of rug pulls in the historical database: mixer funding within 30 days of deployment is the most predictive timing signal. Beyond 30 days, the correlation weakens significantly. This factor is ★ critical because it identifies deployer-level intent, not just code-level capability.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-125',
    title: 'Deployer Linked to DPRK / Lazarus',
    description: 'Why a 3-hop on-chain link from deployer wallet to DPRK/Lazarus cluster is classified as a ★ critical red.',
    factorId: 'RD-F-125',
    body: [
      'The Lazarus Group (DPRK state-sponsored hackers) has stolen billions from DeFi protocols through a combination of social engineering (infiltrating teams as developers), direct exploitation, and bridge attacks. Wallets used in confirmed Lazarus operations form a cluster that can be traced on-chain via Chainalysis and similar tools.',
      'When a protocol deployer\'s wallet is linked within 3 on-chain hops to this cluster, the risk profile changes categorically: it is not just a rug risk but a state-actor risk. The Bybit exchange ($1.4B, 2025) and Radiant Capital ($50M) are documented Lazarus operations where the attack vector included infiltration of developer positions. This factor is ★ critical with no practical mitigation path; the linkage itself is the signal.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-123',
    title: 'Sudden ACL Change Without Discussion',
    description: 'Why an admin-rescue or access-control change with no preceding governance discussion is an insider implant signal.',
    factorId: 'RD-F-123',
    body: [
      'Legitimate administrative changes in mature protocols are preceded by governance discussions, forum posts, or at minimum a GitHub issue. A sudden change to access control (a new role granted, an emergency function enabled, admin transferred) without any public deliberation is a strong signal of either insider threat activity (a compromised or malicious team member acting unilaterally) or preparation for an extraction event.',
      'This factor grades the process, not just the outcome. The same ACL change with a documented reason and community discussion is operationally acceptable; the same change executed silently is a red flag. The historical database includes multiple cases where a sudden ACL change was the final step before a rug pull, executed when TVL peaked.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-151',
    title: 'Bridge ecrecover Zero-Address Check Missing',
    description: 'How the Wormhole class of bridge exploits works: a missing return value check on ecrecover.',
    factorId: 'RD-F-151',
    body: [
      'The ecrecover Solidity function recovers the signer address from a signature. When the signature is invalid, ecrecover returns address(0), the zero address. If a bridge contract doesn\'t check that the recovered address is not address(0), a signature with an all-zero s value passes validation trivially: ecrecover returns 0x000...000, which passes any "is this a known validator" check if address(0) is in the validator set (or if the check is absent).',
      'The Wormhole exploit ($320M) used this exact mechanism. The contract verified that a guardian\'s signature was present but didn\'t reject signatures where ecrecover returned address(0). One line of missing validation, if (signer == address(0)) revert(), would have prevented the loss.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-154',
    title: 'Zero Default Value as Valid Bridge Root',
    description: 'How the Nomad $190M exploit worked: zero-initialized state that made every message valid.',
    factorId: 'RD-F-154',
    body: [
      'Nomad bridge validated cross-chain messages by checking them against a "committed root", a hash representing valid message state. During an upgrade, the trusted root was initialized to bytes32(0) (all zeros) rather than a real root. Because the validation check was require(committedRoot[_root] == true), and zero was now a valid root, any message with a zero root passed validation automatically.',
      'The result: any message, including fraudulent ones claiming arbitrary token transfers, was accepted as valid. The exploit was fully public and permissionless; anyone who noticed could copy the attack transaction and drain funds. Approximately $190M was lost in a chaotic free-for-all as hundreds of wallets replicated the attack within minutes of the first exploitation.',
    ],
  },
  {
    type: 'factor',
    slug: 'RD-F-180',
    title: 'Immutable Oracle Address',
    description: 'Why hardcoding an oracle address with no admin-replaceable wrapper is a ★ critical risk in any substrate.',
    factorId: 'RD-F-180',
    body: [
      'When an oracle address is immutable, set at deployment and not changeable by any admin action short of a full protocol upgrade, the protocol loses the ability to respond to oracle failures, compromises, or manipulations. If the oracle becomes unreliable or is deprecated, every user is exposed until a full upgrade can be deployed, audited, and executed through governance.',
      'This factor was promoted to ★ critical in April 2026 (T-14 promotion) after four documented incidents in 14 months: USR (Apr 2026), USDX (Mar 2026), xUSD (Nov 2025), and USD0++ (Jan 2025). In each case, an immutable oracle address left the protocol unable to respond when the oracle behaviour changed. The mitigation is an admin-replaceable wrapper with appropriate governance controls around the replacement action.',
    ],
  },
];

// ── Chain topics (10) ─────────────────────────────────────────────────────────

const CHAINS: LearnTopic[] = [
  {
    type: 'chain',
    slug: 'ethereum',
    title: 'Ethereum | DeFi Risk Profile',
    description: 'The risk landscape for DeFi protocols deployed on Ethereum mainnet.',
    chainName: 'Ethereum',
    relatedFactors: ['RD-F-001', 'RD-F-027', 'RD-F-053'],
    body: [
      'Ethereum mainnet is the primary settlement layer for DeFi. It hosts the largest protocols by TVL and the most mature governance systems. Its slower block times (12 seconds post-Merge) relative to L2s mean flash loan attacks require slightly longer transactions, but the high liquidity of Ethereum DEXs makes flash loan sources widely available.',
      'Ethereum protocols in the risk database show a wide grade distribution: the chain hosts some of the most secure protocols in DeFi (Aave v3, Uniswap v4) alongside many that have been exploited. The maturity of the chain means auditing tooling, formal verification, and governance frameworks are most developed here.',
    ],
  },
  {
    type: 'chain',
    slug: 'bsc',
    title: 'BNB Smart Chain (BSC) | DeFi Risk Profile',
    description: 'The risk landscape for DeFi protocols on BNB Smart Chain, historically the most exploit-dense chain by incident count.',
    chainName: 'BSC',
    relatedFactors: ['RD-F-043', 'RD-F-070', 'RD-F-053'],
    body: [
      'BNB Smart Chain (BSC) has historically had the highest raw count of DeFi exploits by protocol count. The low deployment cost, EVM compatibility, and large retail user base attracted many protocols launched by anonymous teams with minimal security investment. Flash loan attacks were especially prevalent due to PancakeSwap\'s role as a primary price source.',
      'BSC protocols in the hacks database include disproportionate representation of Compound V2 forks exploited via empty-market manipulation, rug pulls enabled by deployer-EOA admin retention, and spot-pool oracle exploits. Protocols on BSC that grade well typically have explicit Ethereum-parity security practices rather than relying on chain-specific expectations.',
    ],
  },
  {
    type: 'chain',
    slug: 'polygon',
    title: 'Polygon | DeFi Risk Profile',
    description: 'The risk landscape for DeFi protocols on Polygon PoS.',
    chainName: 'Polygon',
    relatedFactors: ['RD-F-053', 'RD-F-151'],
    body: [
      'Polygon PoS was an early scaling solution for Ethereum-based DeFi and attracted significant TVL during 2021–2022. Its exploit history is smaller than BSC but includes notable bridge incidents and oracle manipulation exploits. The chain\'s faster finality relative to Ethereum makes some real-time signal factors harder to enforce.',
      'The Polygon bridge itself has been a security focus area, with the cross-chain category (Cat 10) factors being particularly relevant for protocols that bridge assets between Polygon and Ethereum mainnet.',
    ],
  },
  {
    type: 'chain',
    slug: 'arbitrum',
    title: 'Arbitrum | DeFi Risk Profile',
    description: 'The risk landscape for DeFi protocols on Arbitrum One.',
    chainName: 'Arbitrum',
    relatedFactors: ['RD-F-001', 'RD-F-027'],
    body: [
      'Arbitrum One is an Ethereum optimistic rollup that has become a major DeFi hub. Its fast finality and Ethereum security inheritance make it attractive for protocols that prioritize security without sacrificing throughput. The Arbitrum ecosystem has seen fewer exploits per TVL-dollar than BSC or Polygon, but notable incidents have occurred.',
      'Protocols deploying on Arbitrum often port Ethereum-based code directly, meaning audit coverage from Ethereum deployments may or may not extend to the L2 deployment. DeFi Risk grades audit scope mismatch (RD-F-001) based on whether the Arbitrum deployment specifically is within audit scope.',
    ],
  },
  {
    type: 'chain',
    slug: 'optimism',
    title: 'Optimism | DeFi Risk Profile',
    description: 'The risk landscape for DeFi protocols on OP Mainnet.',
    chainName: 'Optimism',
    relatedFactors: ['RD-F-001', 'RD-F-053'],
    body: [
      'OP Mainnet is an Ethereum optimistic rollup focused on public goods and ecosystem grants. It shares much of its DeFi stack with Ethereum mainnet (Uniswap, Aave, Synthetix deployed here), and these protocols inherit their Ethereum security assessments to a significant degree. Native OP protocols have a smaller audit track record.',
      'The OP Stack\'s fraud proof mechanism provides an additional security layer for bridge withdrawals, but protocols that use optimistic bridging for internal logic inherit the dispute window risk. Cat 10 cross-chain factors are relevant for any OP Stack protocol with cross-chain message passing.',
    ],
  },
  {
    type: 'chain',
    slug: 'avalanche',
    title: 'Avalanche | DeFi Risk Profile',
    description: 'The risk landscape for DeFi protocols on Avalanche C-Chain.',
    chainName: 'Avalanche',
    relatedFactors: ['RD-F-070', 'RD-F-053'],
    body: [
      'Avalanche C-Chain is EVM-compatible and attracted significant DeFi activity during the 2021–2022 bull market via the Avalanche Rush incentive program. The chain\'s sub-second finality is a security positive for real-time signal monitoring but does not mitigate smart contract vulnerabilities.',
      'Avalanche\'s exploit history includes Compound V2 fork incidents (empty-market pattern) and spot-oracle manipulation exploits, similar to BSC. Protocols with AVAX-specific oracle sources should be assessed against the WAVAX/USD oracle quality, as deep liquidity Chainlink feeds for AVAX have historically been more reliable than for long-tail assets.',
    ],
  },
  {
    type: 'chain',
    slug: 'solana',
    title: 'Solana | DeFi Risk Profile',
    description: 'The risk landscape for DeFi protocols on Solana, a non-EVM high-performance blockchain.',
    chainName: 'Solana',
    relatedFactors: ['RD-F-180', 'RD-F-001'],
    body: [
      'Solana is the primary non-EVM chain in the DeFi Risk v1 coverage universe. Its account-model architecture and Rust-based programs require a different security evaluation approach than EVM Solidity contracts. Audit tooling (Solana-specific auditors like OtterSec, Trail of Bits\' Solana practice) is less mature than the EVM ecosystem.',
      'The immutable oracle address factor (RD-F-180) is substrate-agnostic and applies to Solana programs that hardcode oracle addresses. Solana\'s Pyth network is the primary oracle, and protocols that use Pyth correctly with confidence-interval checks grade better than those that use raw price feeds without staleness protection.',
    ],
  },
  {
    type: 'chain',
    slug: 'fantom',
    title: 'Fantom | DeFi Risk Profile',
    description: 'The risk landscape for DeFi protocols on Fantom Opera.',
    chainName: 'Fantom',
    relatedFactors: ['RD-F-053', 'RD-F-043'],
    body: [
      'Fantom Opera hosted significant DeFi activity from 2021 to 2023, driven by the Yearn Finance ecosystem and the Tomb Finance algorithmic stablecoin. Its exploit history includes oracle manipulation and algorithmic stablecoin collapses.',
      'Fantom\'s TVL has declined substantially since the collapse of several native protocols. Remaining protocols often have smaller user bases and less frequent auditing cycles. DeFi Risk\'s Cat 4 economic risk factors are particularly relevant for Fantom-native protocols given the chain\'s history of algorithmic stablecoin failures.',
    ],
  },
  {
    type: 'chain',
    slug: 'zksync',
    title: 'zkSync Era | DeFi Risk Profile',
    description: 'The risk landscape for DeFi protocols on zkSync Era, an Ethereum ZK rollup.',
    chainName: 'zkSync',
    relatedFactors: ['RD-F-001', 'RD-F-139'],
    body: [
      'zkSync Era is an Ethereum ZK rollup that uses validity proofs rather than fraud proofs. Its cryptographic security guarantees for L1 finality are stronger than optimistic rollups, but smart contract vulnerabilities remain independent of the ZK proving system; the proof verifies computation, not intent.',
      'Several Ethereum-native protocols (Uniswap, Aave, Curve) have deployed on zkSync Era. For these, audit coverage from Ethereum deployments may or may not include the zkSync-specific deployment. DeFi Risk assesses whether zkSync deployments are within the scope of existing audits (RD-F-001).',
    ],
  },
  {
    type: 'chain',
    slug: 'base',
    title: 'Base | DeFi Risk Profile',
    description: 'The risk landscape for DeFi protocols on Base, Coinbase\'s Ethereum L2.',
    chainName: 'Base',
    relatedFactors: ['RD-F-053', 'RD-F-027'],
    body: [
      'Base is an Ethereum optimistic rollup built on the OP Stack and operated by Coinbase. Its association with a regulated centralized exchange has attracted retail-focused DeFi protocols and created a distinct ecosystem from other OP Stack chains. Base\'s rapid TVL growth in 2024 attracted both legitimate protocols and opportunistic deployments.',
      'The chain\'s fast growth has created a gap between TVL and audit maturity for many Base-native protocols. DeFi Risk\'s Cat 1 (Code & Audits) and Cat 2 (Governance) factors are the primary risk vectors for Base protocols given this maturity gap.',
    ],
  },
];

// ── Public API ────────────────────────────────────────────────────────────────

export const ALL_TOPICS: LearnTopic[] = [...EXPLOITS, ...FACTORS, ...CHAINS];

export const TOPICS_BY_TYPE: Record<TopicType, LearnTopic[]> = {
  exploit: EXPLOITS,
  factor: FACTORS,
  chain: CHAINS,
};

export function getTopic(type: TopicType, slug: string): LearnTopic | undefined {
  return TOPICS_BY_TYPE[type].find((t) => t.slug === slug);
}

export function getTopicsByType(type: TopicType): LearnTopic[] {
  return TOPICS_BY_TYPE[type];
}
