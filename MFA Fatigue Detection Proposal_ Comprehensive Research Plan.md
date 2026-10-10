# **REVIEW-I READY RESEARCH PACK: Multi-Factor Authentication Fatigue Attack Detector**

## **1\. Formal Problem Definition and Theoretical Foundations**

### **1.1 Understanding Multi-Factor Authentication Fatigue**

Multi-Factor Authentication (MFA) Fatigue represents a critical vulnerability at the intersection of cryptographic security and human psychology. Tracked by the MITRE ATT\&CK framework under the designation Multi-Factor Authentication Request Generation (T1621), the attack is colloquially known as MFA bombing, push bombing, or prompt spamming1. The fundamental premise of the attack is that an adversary has already successfully compromised a victim's primary credentials—typically a valid username and password obtained through credential stuffing, phishing, or dark web marketplaces2. Because the adversary lacks access to the secondary authentication factor (such as an authenticator application or physical token), they cannot autonomously complete the login sequence.  
To circumvent this control, the adversary abuses the automatic generation of push notifications inherent in modern identity and access management (IAM) solutions like Microsoft Entra ID, Okta, and Duo Security3. The attacker initiates continuous and repetitive login attempts, which trigger a relentless barrage of MFA push notifications, SMS messages, or automated phone calls to the victim's device3. The attack leverages the psychological phenomena of decision fatigue, cognitive depletion, and habituation. The adversary operates on the assumption that the victim, overwhelmed by the unending alerts, will eventually capitulate and approve a request simply to silence the device, or will do so inadvertently out of muscle memory2.

### **1.2 Attack Workflow and Real-World Threat Actors**

The anatomy of an MFA fatigue campaign follows a highly structured workflow designed to maximize user friction and cognitive overload2. Upon acquiring valid primary credentials, the adversary initiates the authentication request from an unauthorized geographic location or device. Because the credentials are correct, the Identity Provider (IdP) assumes legitimate intent and forwards the secondary challenge to the user4. The request generation phase then commences. This can manifest as high-velocity "bombing," where hundreds of requests are dispatched within minutes, or as a "low-and-slow" campaign, pacing requests to remain below the detection thresholds of static rate-limiting rules4.  
Advanced persistent threat (APT) groups and sophisticated cybercriminal syndicates have successfully weaponized this technique. For instance, threat actors tracked as Scattered Spider and LAPSUS$ have prominently utilized MFA fatigue to breach highly secured enterprise environments3. In numerous documented cases, these adversaries have augmented the digital bombardment with out-of-band social engineering11. The attacker may contact the victim via SMS or phone, impersonating corporate IT support, and instruct the victim to approve the prompt to resolve a fabricated synchronization issue8. Once the victim approves a single request, the adversary gains initial access, immediately registering a rogue device (such as an attacker-controlled FIDO2 key or authenticator application) to establish persistence2. This persistence allows the adversary to bypass the victim's device entirely during subsequent logins, facilitating lateral movement, data exfiltration, and ransomware deployment.

### **1.3 Security Impact and Affected Environments**

The security implications of MFA fatigue are profound, as the attack subverts the exact control designed to mitigate credential theft. While the Cybersecurity and Infrastructure Security Agency (CISA) strongly advocates for phishing-resistant MFA (such as hardware-bound FIDO2 tokens), the reality is that the vast majority of enterprise identity systems, cloud services, and remote workforce VPNs still rely on vulnerable push-notification mechanisms12. Administrator accounts and highly privileged service accounts are prime targets; compromising a single identity can grant an adversary keys to the entire corporate infrastructure14. The financial losses from resulting breaches, combined with regulatory penalties and reputational damage, position MFA fatigue as a premier threat to modern zero-trust architectures11.

### **1.4 Current Technical Challenges in Detection**

Detecting MFA fatigue dynamically remains a significant challenge for modern security operations centers (SOCs) due to the legitimate nature of the authentication infrastructure being abused9. The primary difficulties include distinguishing between a malicious attack and a legitimate burst of requests. Network latency, poor cellular reception, or desynchronized application states frequently cause legitimate users to manually trigger multiple MFA prompts in rapid succession17. Traditional detection mechanisms rely on static rate limiting, which blindly blocks accounts after a predefined threshold16. This rigid approach generates high rates of false positives, locking out legitimate personnel and inflating helpdesk overhead2.  
Furthermore, standard identity providers suffer from contextual blindness. They process MFA events as binary outcomes (approved or denied) without temporally correlating the sequence of events5. The latency of a user's response, the consecutive streak of denials preceding an approval, and the velocity of geographic shifts between the primary login and the secondary approval device are rarely analyzed holistically in real time. Consequently, threshold-based systems fail to detect low-and-slow attacks, while over-sensitive alerting rules result in alert fatigue for security analysts6.

## **2\. Comprehensive Academic Literature Survey (2022–2026)**

A rigorous survey of recent academic literature published between 2022 and 2026 reveals a growing consensus on the vulnerabilities of push-based authentication and the necessity for behavioral anomaly detection. The following analysis synthesizes ten highly relevant, peer-reviewed sources that form the theoretical foundation for the proposed research.  
The first critical area of literature focuses on the empirical evaluation of current MFA mitigations. In their 2024 study published in IEEE Transactions on Mobile Computing, Jabour et al. investigated the efficacy of "Push-Compare-and-Confirm" protocols, commercially known as number matching18. Their objective was to determine if forcing a user to match a code displayed on a terminal with their mobile device mitigated concurrency and fatigue attacks. Through a comprehensive user study involving 65 participants across 24 login trials, the researchers discovered a glaring limitation. While usability remained high in benign scenarios, users correctly identified only approximately fifty percent of fraudulent login attempts during active attack simulations18. This paper establishes a fundamental baseline: human-reliant friction, such as number matching, is statistically insufficient to prevent MFA fatigue due to persistent human error, necessitating an automated detection backend.  
Building upon the psychology of human error, a 2025 synthesis in the Journal of Information Systems Engineering and Management explored the impact of decision fatigue on cybersecurity vulnerabilities within university environments7. The research utilized ego depletion theory to model how prolonged cognitive demands deteriorate a user's ability to evaluate risk7. The findings were stark, demonstrating that fatigued individuals exhibited a forty-two percent higher likelihood of falling for social engineering and reflexively approving malicious security prompts7. This literature is highly relevant as it provides the psychological justification for shifting the defensive burden away from the end-user and onto algorithmic anomaly detection systems.  
In the realm of detection engineering, Green (2026) proposed a defender-centric strategy for identifying MFA fatigue and Adversary-in-the-Middle (AiTM) attacks in the International Journal of Health, Education & Social19. The objective was to fuse identity telemetry—specifically push frequency anomalies and impossible travel metrics—with endpoint signals. Evaluated across fifteen organizations, the methodology reduced median time-to-detect by sixty-three percent and decreased successful account takeovers by forty-one percent19. However, the author noted limitations regarding noisy travel baselines generating false positives for mobile workforces. This study directly supports the proposed project's hypothesis that request frequency must be combined with contextual signals to reduce false positives.  
The application of unsupervised machine learning for authentication anomaly detection is explored deeply in a 2025 study by Nalam, published in the Journal of Computer Science and Technology Studies20. The researcher aimed to develop a dynamic monitoring mechanism capable of identifying unusual activity based on contextual and behavioral indicators without imposing continuous friction on the user. The architecture utilized the Isolation Forest algorithm to detect behavioral anomalies specifically related to request frequency, alongside Generative AI for log summarization20. While the study successfully demonstrated real-time dynamic trust indexing, it limited its use of the Isolation Forest to basic request frequencies rather than exploiting the complex multivariate relationships between response latency and deny streaks. This identifies a clear opportunity for the proposed research to expand upon the feature engineering inputs for the Isolation Forest model.  
Similarly validating the choice of machine learning algorithms, Zola et al. (2024) developed a theoretical framework for decentralized intrusion detection using the Isolation Forest algorithm integrated with blockchain technology21. Their objective was to efficiently identify anomalies in high-velocity network traffic. The methodology proved that Isolation Forest excels in environments with unlabeled data and strict computational overhead constraints21. Although the blockchain integration in their study introduces unnecessary latency for centralized enterprise identity management, the empirical validation of Isolation Forest's scalability and accuracy for streaming network anomalies perfectly aligns with the requirements of processing high-volume authentication logs.  
The necessity of retaining software-based behavioral detection is underscored by Ojo et al. (2026), who analyzed the effectiveness of various MFA modalities in distributed systems22. Their comprehensive review confirmed that while basic MFA mitigates automated credential stuffing, traditional push methods remain acutely vulnerable to prompt fatigue. The study concluded that only FIDO2-compliant passwordless hardware authenticators achieve over 99.9 percent mitigation efficiency against fatigue attacks22. The limitation of this finding is its reliance on universal hardware deployment, which is often economically and operationally prohibitive for large organizations. This solidifies the research gap: there remains a critical need for an intermediate software-based behavioral layer to protect the vast majority of systems still relying on push notifications.  
Further supporting the move toward continuous behavioral analysis, researchers exploring AI for real-time vulnerability assessment in hotel booking platforms demonstrated the power of temporal sequence mining17. The 2024 studies investigated how machine learning can continuously evaluate request frequencies, endpoint access behaviors, and login timing to detect account takeovers that bypass initial authentication. By tracking the exact sequencing of user actions post-login, the AI could flag anomalies that static rules missed17. This methodology is highly relevant, validating the proposed system's approach of engineering features out of the temporal spacing and latency of MFA requests.  
Expanding the scope of unsupervised anomaly detection, the 2025 ANCHOR study evaluated machine learning approaches for IoT connectivity and roaming signaling24. The engineers utilized Isolation Forests to process millions of signaling traffic events, successfully detecting anomalies related to device authentication and mobility patterns that traditional operator alarm systems missed24. The study emphasized that expert-driven feature engineering allowed simpler models like Isolation Forests to outperform highly complex deep learning architectures in terms of latency and interpretability.  
In the cryptographic domain, Nair (2023) presented the Multi-Factor Key Derivation Function (MFKDF) at the USENIX Security Symposium25. While the primary focus was extending password-based key derivation functions to incorporate secondary factors like TOTP, the underlying premise highlights the inherent fragility of relying solely on disconnected push mechanisms25. The research advocates for deeply integrating multiple authentication signals, conceptually supporting the proposed system's holistic aggregation of context, latency, and frequency to derive a unified trust score.  
Finally, a 2024 comparative analysis on synthetic data generation in cybersecurity addresses a critical infrastructural challenge for this research26. The authors highlight the severe lack of publicly available, high-fidelity tabular datasets containing specific cybersecurity logs due to privacy constraints. The study evaluates statistical and generative AI methods for creating synthetic network traffic that mirrors real-world statistical features without exposing sensitive information26. This literature provides the methodological foundation for the synthetic dataset generation strategy that will be required to train and evaluate the proposed Isolation Forest model effectively.

## **3\. Literature Comparison Matrix and Synthesis**

The following matrix structures the core technical findings from the most relevant peer-reviewed literature to facilitate the identification of systemic research gaps.

| Paper / Author | Year | Problem Addressed | Methodology | Data / Environment | Key Result / Strength | Limitation | Relevance to Proposed Project |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| **Green** \[cite: 19\] | 2026 | MFA fatigue & AiTM phishing attacks | Fused identity telemetry (push frequency, geo-travel) with gateway indicators | Enterprise SIEM environments | Reduced detection time by 63%; highly practical implementation | High false positives on "impossible travel" due to mobile workforces | Validates fusing request frequency with contextual signals to improve detection. |
| **Jabour et al.** \[cite: 18\] | 2024 | Concurrency and fatigue attacks in Push 2FA | Usability study on "Push-Compare-and-Confirm" (Number Matching) | N=65 user trials; benign vs. attack scenarios | Users identified only \~50% of fraudulent logins under duress | Focuses on human factors; lacks an automated detection backend | Proves that human-reliant friction (number matching) is insufficient without AI oversight. |
| **Al-Kindi (Nalam)** \[cite: 20\] | 2025 | Lack of dynamic behavioral authentication | GenAI for logs \+ Isolation Forest for anomaly detection | Web authentication telemetry | Real-time dynamic trust indexing without added user friction | Isolation Forest used solely for basic request frequency | Justifies the selection of Isolation Forest for low-latency anomaly detection. |
| **Gokaraju et al.** \[cite: 7\] | 2025 | Decision fatigue and cyber vulnerabilities | Structural equation modeling of user stress and security behavior | University student populations | Fatigued users are 42% more likely to fall for attacks | Focuses heavily on policy/psychology rather than technical defense | Validates the premise that human users will inevitably fail under fatigue. |
| **Zola et al.** \[cite: 21\] | 2024 | Decentralized intrusion detection | Isolation Forest integrated with blockchain smart contracts | Network traffic datasets | Scalable, efficient unsupervised anomaly detection | Blockchain adds unnecessary latency for centralized IAM | Confirms Isolation Forest as an optimal ML algorithm for high-speed logs. |
| **Ojo et al.** \[cite: 22\] | 2026 | Evaluating MFA efficacy against modern threats | Empirical telemetry analysis of MFA modalities | Enterprise identity environments | Push MFA is highly vulnerable; FIDO2 is 99.9% effective | Relies entirely on hardware rollout (FIDO2) as the ultimate solution | Highlights the need to protect legacy push-MFA via software monitoring. |
| **Hotel ATO Analysis** \[cite: 23\] | 2024 | Account takeovers post-authentication | Continuous behavioral monitoring framework | Reservation platform logs | Demonstrated that tracking request sequencing reveals hidden anomalies | Fraud-focused; not optimized specifically for MFA push metadata | Validates using behavioral features (timing, request velocity) for AI risk scoring. |
| **Synthetic Data in Cyber** \[cite: 26\] | 2024 | Lack of public cybersecurity datasets | Evaluation of statistical/AI data generation methods | Tabular network traffic | Identified optimal methods for preserving statistical fidelity in synthetic data | Complex generative models are computationally heavy | Informs the synthetic data generation strategy required for model training. |

### **Synthesis of the Literature**

A critical synthesis of the literature reveals clear trends regarding how researchers and the cybersecurity industry are approaching MFA fatigue. The prevailing paradigm heavily favors shifting the burden of verification. Solutions either shift the burden back to the user by introducing friction (e.g., Number Matching)18, or they attempt to shift the burden to hardware through cryptographic solutions like FIDO222.  
However, the literature consistently demonstrates the shortcomings of these approaches. Human-centric friction is proven to fail under psychological duress, as users will inadvertently approve fraudulent requests roughly half the time during a concerted attack7. Furthermore, hardware-centric solutions present insurmountable economic and logistical deployment barriers for many organizations. What researchers are currently missing is a robust, software-based middle layer that leverages the metadata of the human-system interaction. While anomaly detection using Isolation Forests is being applied to network traffic and basic authentication frequencies, researchers are failing to capture the nuanced temporal sequencing of a fatigue attack—specifically the latency between the prompt and the user's response, and the consecutive streak of behavioral denials prior to an approval20.

## **4\. Analysis of Existing Solutions and Mitigation Strategies**

The cybersecurity industry currently deploys several mechanisms to combat MFA fatigue, ranging from basic configuration changes to advanced commercial identity protections. Distinguishing between general best practices, commercial mechanisms, and research prototypes is essential for understanding the operational landscape.

| Existing Solution / Approach | Type | How It Works | Advantages | Limitations | Relevance to Project |
| :---- | :---- | :---- | :---- | :---- | :---- |
| **Number Matching (e.g., Microsoft Authenticator)** | Commercial Security Mechanism | Displays a 2-digit number on the login terminal that the user must manually type into their mobile authenticator app27. | Eliminates "one-tap" reflex approvals; forces the user to prove physical proximity to the session requesting access. | Degrades user experience via daily friction; vulnerable to sophisticated social engineering (attacker reading the number over the phone)11. | Represents the industry standard. The proposed system will dynamically trigger this friction only when high risk is detected. |
| **Static Rate Limiting (IdP Throttling)** | Industry Best Practice | Enforces rigid thresholds (e.g., blocking an account or pausing prompts if more than 3 requests are generated in 5 minutes)6. | Easy to configure within existing IAM panels; effectively mitigates crude, high-velocity automated push scripts. | Rigid logic generates high false positives during network sync issues; effortlessly bypassed by adversaries pacing their attacks (low-and-slow)2. | Serves as the baseline model. The proposed ML system will serve as an intelligent, dynamic alternative to these rigid thresholds. |
| **FIDO2 / WebAuthn Hardware Keys** | Cryptographic Standard / Hardware Solution | Utilizes public key cryptography bound to the specific web origin, requiring a physical hardware token (e.g., YubiKey) to authenticate27. | The gold standard for phishing resistance; completely immune to push fatigue, AiTM, and SIM swapping22. | High deployment and replacement costs; severe lack of support across legacy applications; creates significant IT support overhead27. | Illustrates the ideal end-state of authentication, but highlights the immediate need to secure environments locked into software push MFA. |
| **Static SIEM Rules (e.g., Splunk)** | Security Monitoring | Security analysts write Boolean logic rules to trigger alerts (e.g., IF deny\_count \> 3 AND geo \!= historical\_geo THEN alert)4. | Highly customizable; integrates seamlessly with existing enterprise log aggregation infrastructure. | Generates massive alert fatigue; entirely reactive rather than preventative; cannot easily detect non-linear or multi-dimensional behavioral anomalies. | The proposed AI engine will automate and vastly improve upon manual rule creation by recognizing complex patterns. |
| **Risk-Based / Adaptive Authentication** | Commercial / Research Hybrid | Evaluates environmental context (IP reputation, device trust, geographic location) before issuing an MFA challenge15. | Reduces the overall volume of unnecessary prompts, limiting the attack surface; transparent to the end-user when risk is low. | Commercially expensive; heavily reliant on network indicators rather than analyzing the user's specific interactive behavior during the prompt sequence itself. | Validates the concept of dynamic risk scoring. The proposed system extends this by incorporating interactive behavioral metrics. |

## **5\. Identification of Defensible Research Gaps**

Based on the synthesis of the academic literature and the analysis of existing commercial solutions, three highly defensible research gaps have been identified. The crux of these gaps centers on the systemic failure to combine temporal request patterns with human interactive behavioral signals.

### **Gap 1: Inadequacy of Static Thresholds Against Temporal Attack Variations**

* **Existing State of the Art:** Current identity platforms predominantly utilize static rate-limiting to curb MFA fatigue. A system is configured to block access if a hardcoded threshold—such as five prompts in fifteen minutes—is breached6.  
* **Limitation:** This rigid logic fails on two fronts. First, it is effortlessly bypassed by adversaries employing "low-and-slow" techniques, who simply space their requests out every twenty minutes to remain undetected. Second, it generates severe false positives when a legitimate user experiences transient network desynchronization, resulting in account lockouts2.  
* **Why the Limitation Matters:** Static thresholds force organizations into a zero-sum tradeoff between usability and security. Alert fatigue paralyzes SOC teams tasked with investigating thousands of false positive lockouts9.  
* **Unresolved Issue:** The industry lacks a dynamic anomaly detection mechanism capable of evaluating the *burstiness* and non-linear temporal distribution of requests rather than relying on absolute arithmetic counts.

### **Gap 2: Neglect of User Response Behavioral Signals in Authentication Telemetry**

* **Existing State of the Art:** Contemporary detection engines evaluate MFA events as binary outcomes: the prompt was either "Approved," "Denied," or "Timed Out"9.  
* **Limitation:** This binary classification ignores the rich, high-fidelity behavioral metadata embedded in the *latency* of the response and the *streak* of user actions7. For example, a user who denies three requests in three seconds, experiences a thirty-minute delay, and then suddenly approves a request in one second exhibits a quintessential behavioral signature of fatigue capitulation2.  
* **Why the Limitation Matters:** By ignoring how long it takes a user to interact with a prompt, systems discard the most vital indicator of human cognitive state and habituation7.  
* **Unresolved Issue:** Current research and commercial systems do not leverage "Response Latency" or "Deny Streaks" as primary predictive features for authentication anomaly detection.

### **Gap 3: The Usability vs. Friction Dichotomy in Mitigation Application**

* **Existing State of the Art:** Organizations currently choose between highly frictionless push notifications (which are deeply vulnerable to fatigue) or enforcing Number Matching on every single login (which induces high daily friction)27.  
* **Limitation:** Applying maximum friction indiscriminately degrades the user experience and impacts enterprise productivity without proportionally increasing security for low-risk logins.  
* **Unresolved Issue:** There is a distinct absence of a continuous, risk-based escalation mechanism that operates invisibly, utilizing behavioral analysis to selectively step-up authentication friction (e.g., forcing Number Matching) only when anomalous temporal or contextual behavior is detected32.

**Investigation of the Proposed Direction:** The hypothesis of combining MFA request frequency with user response behavior (latency and streaks) and contextual signals (geography and IP) is highly defensible. An investigation into recent literature confirms that while risk-based authentication evaluating geographic context is common commercially15, the specific algorithmic fusion of *push-response latency* with *temporal burstiness* utilizing unsupervised machine learning remains an underexplored academic frontier20.

## **6\. Proposed Novelty and Hypothesis Formulation**

Drawing upon the established research gaps, the proposed project will pivot away from static network-level intrusion detection and focus entirely on human-behavioral interaction detection during the secondary authentication phase.

### **Recommended Novelty Direction: Hybrid Behavioral-Contextual Detection via Isolation Forest**

The core novelty of this project is the design and implementation of a monitoring engine that abandons static MFA request thresholds in favor of an unsupervised machine learning algorithm. This engine will continuously evaluate the multi-dimensional relationship between temporal request burstiness, user response latency, consecutive denial streaks, and contextual anomalies to generate a dynamic risk score.

* **Research Gap Addressed:** This approach directly mitigates the inadequacy of static thresholds against low-and-slow attacks (Gap 1\) and pioneers the use of interactive response latency as a primary threat indicator (Gap 2).  
* **Technical Mechanism:** The system will asynchronously ingest real-time authentication logs. A feature engineering module will extract continuous variables such as the trailing fifteen-minute request velocity, average response latency in seconds, and the sequence of consecutive denials. An Isolation Forest algorithm will process these vectors to calculate an anomaly score. This score is then normalized into a Risk Level, which triggers dynamic system responses ranging from silent approval to session blocking.  
* **Why it is Academically Novel:** This methodology is conceptually novel because it treats the human user's interaction timing as a measurable biometric signature of fatigue. It fundamentally differs from existing work like Microsoft's Number Matching, which is a static UI intervention27, and traditional SIEM alerting, which relies on hardcoded Boolean logic4.  
* **Implementation Feasibility and Defensibility:** Selecting the Isolation Forest algorithm is a highly calculated decision that ensures student-level feasibility while maximizing academic rigor. Unlike supervised algorithms such as XGBoost, Random Forest, or Deep Neural Networks, the Isolation Forest is an unsupervised technique21. It isolates anomalies by randomly partitioning data; because anomalies are rare and distinct, they require fewer partitions to isolate, resulting in shorter path lengths in the underlying trees21. Supervised models would require massive, perfectly balanced datasets of labeled MFA attacks to train effectively. Because such datasets are proprietary and largely unavailable to the public, attempting supervised learning would render the evaluation scientifically weak26. The Isolation Forest circumvents this by modeling the baseline of normal authentication behavior and flagging deviations, making it highly defensible during a viva voce examination21.

## **7\. Baseline vs. Proposed Method Comparison**

To quantitatively demonstrate the improvement offered by the novelty, the evaluation must compare the proposed system against a standard industry baseline.

| Evaluation Aspect | Baseline Method (Static Threshold) | Proposed Method (Behavioral-Contextual ML) |
| :---- | :---- | :---- |
| **Detection Signals** | Total count of MFA requests over a fixed time window. | Request velocity, response latency, deny streaks, IP changes, device context. |
| **Detection Method** | Hardcoded Boolean logic (e.g., IF count \> 5 THEN block)6. | Unsupervised Machine Learning (Isolation Forest anomaly scoring)33. |
| **Context Awareness** | None. Treats a request from the corporate office identical to a request from a foreign proxy. | High. Correlates request frequency with geographic and device state shifts5. |
| **False Positive Handling** | Poor. Legitimate bursts due to poor connectivity trigger automatic lockouts2. | Excellent. Understands that a burst with normal latency from a known IP is benign. |
| **Adaptability** | Rigid. Must be manually tuned by security analysts as attack patterns evolve. | Dynamic. Continuously models normal behavior, adapting to the user's specific baseline. |
| **Computational Complexity** | Extremely low (![][image1] counting). | Low to Moderate (Isolation Forest is highly efficient for streaming tabular data)21. |

The expected benefit is a measurable reduction in the False Positive Rate (FPR) during simulated benign burst events, alongside a significant decrease in Detection Latency during low-and-slow simulated fatigue attacks.

## **8\. Proposed System Design and Feature Engineering**

### **8.1 System Objective**

The objective is to design, implement, and evaluate an intelligent monitoring system that ingests real-time multi-factor authentication telemetry, extracts engineered temporal and behavioral features regarding user interaction, and utilizes an Isolation Forest anomaly detection engine to calculate a dynamic risk score. This system aims to reliably detect MFA fatigue attacks while minimizing false positive lockouts for legitimate users.

### **8.2 System Inputs**

The system is designed to consume standard JSON telemetry generated by enterprise Identity Providers (e.g., Okta System Logs or Microsoft Entra ID logs)9. The absolute minimum raw data points required include:

* event\_timestamp: The precise epoch time the MFA challenge was issued by the IdP.  
* response\_timestamp: The precise epoch time the user interacted with the prompt on their device.  
* response\_status: The terminal state of the prompt (e.g., ACCEPT, DENY, TIMEOUT).  
* user\_id: A unique, anonymized identifier for the target account.  
* source\_ip: The IP address from which the primary login attempt originated.  
* device\_id: A unique fingerprint of the device initiating the login, compared against the device receiving the push.

### **8.3 Feature Engineering**

Raw logs are insufficient for machine learning. A preprocessing module will continuously transform the raw stream into the following engineered features, carefully selected to capture the essence of a fatigue attack:

> 1. req\_velocity\_15m: The continuous count of MFA requests generated for a specific user\_id in the trailing 15-minute rolling window. (Captures aggressive, high-velocity bombing).  
> 2. req\_velocity\_12h: The count of requests in the trailing 12-hour window. (Captures low-and-slow campaigns designed to evade 15-minute thresholds).  
> 3. response\_latency: The time delta (in seconds) between event\_timestamp and response\_timestamp. Extreme values indicate anomalies; micro-second responses suggest automated acceptance or deep habituation, while extended delays suggest user confusion32.  
> 4. consecutive\_denies: A stateful integer tracking the unbroken streak of DENY outcomes prior to the current request. An ACCEPT immediately following a high consecutive\_denies value is a massive risk indicator.  
> 5. context\_shift\_score: A weighted scalar representing environmental anomalies, such as impossible travel velocity between the current source\_ip and the user's historical baseline, or a mismatch between the initiating device and the receiving device5.

### **8.4 Detection Methodology and Risk Scoring**

The extracted feature vectors are fed into the pre-trained Isolation Forest model. The model outputs a raw anomaly score, typically ranging from \-1 (highly anomalous) to 1 (normal) depending on the implementation. To ensure usability for SOC analysts, this raw output is normalized using Min-Max scaling into a **Dynamic Risk Score** ranging from 0 to 100\.

* ![][image2]

### **8.5 System Response Matrix**

The calculated Risk Score dynamically dictates the automated response executed by the system via API callbacks to the IdP:

* **Low Risk (0–40):** The transaction proceeds without interference. Standard push notifications are permitted, ensuring zero friction for standard behavior.  
* **Medium Risk (41–75):** Step-up Authentication is triggered. The system intercepts the standard push notification and elevates the requirement, forcing the user to utilize Number Matching or enter a Time-based One-Time Password (TOTP). This disrupts the mindless habituation relied upon by attackers6.  
* **High Risk (76–100):** The session is aggressively terminated. The user account is temporarily locked, active session tokens are revoked, and a critical alert is pushed to the SOC dashboard for manual remediation.

### **8.6 Security Administrator Dashboard**

To provide situational awareness, a web-based dashboard will be developed for security personnel. It will display a global heatmap of MFA request volume, a prioritized queue of high-risk users currently exhibiting fatigue signatures, and an interactive timeline detailing the precise temporal spacing and latency of a selected user's recent prompts.

## **9\. System Architecture and Workflow**

The system architecture is designed as a modular, decoupled pipeline, ensuring data flows logically from ingestion to automated response.

### **9.1 Conceptual Data Flow**

\[IdP Webhook Payload\] ![][image3] \[FastAPI Ingestion Endpoint\] ![][image3] \[Pandas Preprocessing & Feature Extraction\] ![][image3] \[Scikit-Learn Isolation Forest Engine\] ![][image3] \[Risk Score Normalization\] ![][image3] \[Response Logic Router\] ![][image3] \[IdP Enforcement API & Streamlit Dashboard\]

### **9.2 Module Breakdown**

> 1. **Authentication Log Collection Module:**  
   * *Purpose:* Acts as the entry point, receiving real-time JSON payloads representing authentication events.  
   * *Technology:* Asynchronous REST API endpoints.  
> 2. **Behavioral Feature Extraction Module:**  
   * *Purpose:* Translates raw data into statistical indicators.  
   * *Processing:* Interfaces with an in-memory datastore to rapidly retrieve rolling window counts and historical states (e.g., fetching a user's current deny streak in milliseconds)20.  
> 3. **Detection Engine Module:**  
   * *Purpose:* Evaluates the feature vector against the Isolation Forest model to isolate anomalies based on path length calculations.  
> 4. **Risk Scoring and Alerting Module:**  
   * *Purpose:* Normalizes the anomaly score and determines the intervention tier (Low, Medium, High). Dispatches commands to the dashboard and simulates the API call back to the identity provider to enforce the block or step-up.  
> 5. **Visualization Dashboard Module:**  
   * *Purpose:* Consumes data from the alerting module to render real-time charts and investigative timelines for human analysts.

## **10\. Dataset Investigation and Synthetic Generation Strategy**

### **10.1 Investigation of Public Datasets**

A rigorous search for publicly available datasets suitable for training an MFA fatigue detection model reveals a systemic deficiency in the academic community26. Prominent cybersecurity datasets, such as NSL-KDD, CICIDS17, or the Los Alamos National Laboratory (LANL) Comprehensive Cyber Security Event Network dataset, focus heavily on raw network packets, generic active directory events, or password-based anomalies. They fundamentally lack the specific identity-layer metadata required for this research—namely, push\_response\_latency, deny\_streaks, and MFA\_status26.

### **10.2 Synthetic Data Generation (SDG) Strategy**

To overcome the absence of real-world MFA telemetry, a scientifically defensible Synthetic Data Generation (SDG) pipeline will be developed26. The pipeline will utilize statistical distributions to simulate authentic corporate authentication traffic, creating a robust dataset for model training and evaluation.

* **Normal User Behavior (The Baseline):** Logins are generated following standard diurnal enterprise patterns (spikes at 9:00 AM and 1:00 PM). Response latencies are modeled on a normal distribution (e.g., ![][image4] seconds, ![][image5] seconds). Prompt outcomes are heavily weighted toward success (98% ACCEPT, 2% TIMEOUT).  
* **Legitimate Burst Scenarios (Edge Cases):** Simulates a user with poor network connectivity. Generates 3-5 rapid requests from a known historical IP. The latencies indicate TIMEOUTs, culminating in a final ACCEPT with normal latency. This scenario is crucial for training the model to avoid false positives.  
* **High-Velocity MFA Fatigue Attacks:** Simulates an aggressive bombing campaign. Generates 20+ requests within a 10-minute window originating from a new, anomalous IP address. Response latencies are extremely short and frustrated (e.g., ![][image6] seconds), primarily resulting in DENY statuses, until a final simulated capitulation (ACCEPT).  
* **Low-and-Slow Fatigue Attacks:** Simulates advanced evasion tactics. Requests are spaced 20-40 minutes apart, remaining beneath traditional static SIEM thresholds, but maintaining anomalous contextual signatures.

The synthetic generation process will strictly separate the training dataset (comprised exclusively of normal and legitimate burst behavior to train the unsupervised Isolation Forest) from the testing dataset (injected with the synthetic fatigue attacks) to ensure experimental validity.

## **11\. Recommended Technology Stack**

The technology stack is carefully selected to balance enterprise realism with student-level implementation feasibility, prioritizing widely supported, open-source frameworks.

* **Backend Logic and ML Engine:** Python 3.10+  
  * *Justification:* Python is the industry standard for machine learning and data processing. Libraries like scikit-learn provide highly optimized implementations of the Isolation Forest algorithm, while pandas and NumPy are unparalleled for rapid time-series rolling window calculations and complex feature engineering.  
* **API Framework:** FastAPI  
  * *Justification:* FastAPI is extremely fast and natively supports asynchronous request handling, making it the ideal framework to simulate the ingestion of high-velocity, real-time authentication webhooks without bottlenecking the ML engine.  
* **Database and State Management:** Redis and PostgreSQL  
  * *Justification:* Redis, an in-memory data structure store, is critical for tracking high-speed state (such as rolling request counts and deny streaks) with microsecond latency20. PostgreSQL will serve as the persistent relational database for long-term audit logging and historical baseline storage.  
* **Frontend Dashboard:** Streamlit  
  * *Justification:* Streamlit allows for the rapid creation of interactive, data-rich dashboards directly from Python code. This vastly reduces UI development time, allowing the project focus to remain on the machine learning novelty while still delivering a professional interface for the SOC analyst view.  
* **Deployment:** Docker  
  * *Justification:* Containerizing the database, API, and frontend ensures the environment is reproducible, eliminating "works on my machine" issues during the final viva demonstration.

## **12\. Implementation Schedule and Project Planning**

The project execution is divided into discrete, measurable phases to ensure steady progress and comprehensive testing.

| Phase | Module | Primary Tasks | Expected Deliverable | Estimated Effort |
| :---- | :---- | :---- | :---- | :---- |
| **Phase 1** | **Dataset Generation** | Develop Python scripts applying statistical distributions to generate normal and attack authentication logs. | Clean, structured .csv datasets spanning varied scenarios. | 2 Weeks |
| **Phase 2** | **Feature Engineering** | Build modules to calculate rolling windows, response latencies, and deny streaks from raw timestamps. | Transformed feature vectors ready for ML ingestion. | 2 Weeks |
| **Phase 3** | **ML Engine Implementation** | Train the baseline static-threshold logic; configure and train the Isolation Forest model. | Pickled ML models and normalized risk scoring logic. | 3 Weeks |
| **Phase 4** | **Backend API Integration** | Develop FastAPI endpoints to receive simulated real-time auth events and route them to the ML engine. | Functional REST API processing asynchronous requests. | 2 Weeks |
| **Phase 5** | **Dashboard Development** | Build the Streamlit interface to visualize global request volumes, risk scores, and user timelines. | Interactive UI providing real-time situational awareness. | 2 Weeks |
| **Phase 6** | **Testing & Evaluation** | Execute simulated attacks through the complete pipeline; calculate metrics; finalize documentation. | Comprehensive performance reports and final presentation. | 2 Weeks |

## **13\. Testing and Experimental Evaluation Design**

To prove that the proposed novelty provides a technically meaningful contribution, the Isolation Forest system will be rigorously evaluated against the defined Baseline Method (a standard static rule alerting on \> 5 requests in 10 minutes).  
**Experimental Scenarios:**  
Both systems will process the synthetic testing dataset, which contains a randomized mixture of:

> 1. Normal daily user authentications.  
> 2. Legitimate burst events (network sync errors).  
> 3. High-velocity fatigue attacks.  
> 4. Low-and-slow fatigue evasion attacks.

**Evaluation Metrics:**  
The success of the system will not be measured solely by overall accuracy, as the rarity of attacks makes accuracy a misleading metric. Instead, the evaluation will focus on:

* **False Positive Rate (FPR):** This is the most critical metric for identity systems. A high FPR means locking out legitimate users during benign burst events. The proposed system must demonstrate a significantly lower FPR than the baseline.  
* **Detection Latency:** Measured as the number of fraudulent prompts dispatched by the adversary before the system accurately calculates a "High Risk" score and initiates a block.  
* **F1-Score:** The harmonic mean of precision and recall, providing a balanced measure of the model's ability to detect true fatigue attacks without generating false alarms.  
* **ROC-AUC:** Receiver Operating Characteristic \- Area Under Curve will be plotted to visualize the model's discriminative ability across different risk thresholds.

## **14\. Viva Voce Defense Preparation**

The following questions anticipate rigorous academic and technical scrutiny from faculty evaluators, paired with technically honest, evidence-backed answers.  
**Q: What exactly is MFA fatigue, and why doesn't implementing standard MFA stop it?** **A:** MFA fatigue is a sophisticated social engineering attack where an adversary uses stolen primary credentials to spam a legitimate user with push notifications until the user approves one out of frustration, habituation, or cognitive overload3. Standard MFA fails because the cryptographic controls are functioning exactly as designed; the vulnerability lies entirely within human psychology. The user is the weakest link, and attackers exploit this by turning the security mechanism into a weapon of annoyance.  
**Q: Why can't we simply set a threshold limit? For example, automatically blocking the account after three requests?** **A:** Static rate-limiting is a blunt instrument that creates unacceptable operational friction. It causes high false positives for legitimate users experiencing poor cellular connectivity or application sync issues who manually request multiple codes2. More importantly, sophisticated adversaries are fully aware of standard SIEM thresholds and easily bypass them by executing "low-and-slow" attacks, spacing their requests out over several hours to remain under the radar6.  
**Q: What is the exact novelty in your project? Changing a database or UI doesn't count.** **A:** My novelty lies in fundamentally shifting the detection paradigm away from static arithmetic counting to a dynamic, unsupervised machine learning approach utilizing the Isolation Forest algorithm. Instead of just counting requests, my system engineers features out of the *behavioral metadata* of the human interaction—specifically measuring response latency, tracking consecutive deny streaks, and correlating these with contextual IP data to generate a real-time, multivariate risk score33.  
**Q: Why did you choose Isolation Forest instead of advanced techniques like Deep Learning or XGBoost?** **A:** Isolation Forest is an unsupervised anomaly detection algorithm perfectly suited for this specific problem space. Deep Learning and XGBoost are supervised techniques, meaning they require massive datasets of perfectly balanced, ground-truth labeled attack data to train effectively33. Because corporate authentication logs are heavily protected by privacy laws, public datasets of MFA fatigue attacks simply do not exist26. The Isolation Forest circumvents this by modeling the baseline of normal authentication behavior and flagging deviations based on path length isolation, making it both computationally lightweight for real-time streaming and highly defensible academically21.  
**Q: How will your system handle a legitimate user who simply mistyped a code or had a network error and requested three prompts in a row?** **A:** By utilizing multivariate analysis rather than binary thresholds. A legitimate burst usually originates from the user's historically known IP address and trusted device, and the prompt statuses will typically register as "Timeouts" rather than active "Denies." The Isolation Forest models the complex relationship between these variables, statistically recognizing that a burst from a known device with timeout latencies is significantly less risky than a burst originating from an unknown proxy IP featuring rapid, frustrated denials2.  
**Q: What are the limitations of your own system?**  
**A:** The primary limitation is its reliance on the assumption that an attacker will exhibit anomalous behavioral timing. If an adversary perfectly mimics a user's normal login velocity, latency, and geographic location (perhaps via a local malware proxy on the victim's machine), the Isolation Forest may fail to isolate the event. Additionally, the system relies on receiving real-time webhook telemetry from the IdP; network latency between the IdP and the detection engine could delay the automated block response.

## **15\. Review-I Presentation Structure (10–15 Minutes)**

To maximize rubric scoring, the presentation must be structured linearly, explicitly addressing each evaluation criterion.

* **Slide 1: Title Slide (0.5 mins)**  
  * Project Title, Student Name, Registration Number, Guide Name.  
* **Slide 2: Problem Statement & Real-World Impact (1.5 mins)**  
  * Define MFA fatigue and the attack workflow (credential theft ![][image3] bombardment ![][image3] capitulation ![][image3] persistence).  
  * Mention real-world impact (e.g., LAPSUS$, Scattered Spider breaches) and target users (SOC teams).  
* **Slide 3 & 4: Literature Survey & Matrix (2 mins)**  
  * Present the literature comparison matrix. Highlight Green (2026) regarding telemetry fusion and Jabour (2024) regarding the failure of human-reliant number matching.  
* **Slide 5: Analysis of Existing Solutions (1.5 mins)**  
  * Table comparing Static Rate Limiting, Number Matching, and FIDO2.  
  * Highlight the core limitation: the industry forces a tradeoff between severe user friction and vulnerability to social engineering.  
* **Slide 6: Identified Research Gaps (1 min)**  
  * Explicitly state the gaps: (1) Inadequacy of static thresholds against low-and-slow attacks, (2) Neglect of user response behavioral signals (latency/streaks).  
* **Slide 7: Proposed Novelty (2 mins)**  
  * Define the novelty: An unsupervised ML (Isolation Forest) engine that leverages response latency, deny streaks, and burstiness for dynamic risk scoring, moving beyond static threshold counting.  
* **Slide 8: Proposed System Architecture (1.5 mins)**  
  * Display a clean, high-level flowchart: IdP Webhook ![][image3] FastAPI Ingestion ![][image3] Feature Extraction ![][image3] Isolation Forest ![][image3] Risk Scoring ![][image3] Dashboard/Response.  
* **Slide 9: Technology Stack (1 min)**  
  * Visual icons for Python, FastAPI, Scikit-learn, Redis, and Streamlit. Briefly justify the use of Redis for high-speed state tracking.  
* **Slide 10: Dataset Strategy (1 min)**  
  * Acknowledge the lack of public MFA telemetry datasets. Outline the scientifically rigorous Synthetic Data Generation strategy using statistical distributions to model normal vs. attack behavior.  
* **Slide 11: Implementation & Testing Plan (2 mins)**  
  * Show the module-wise Gantt chart.  
  * Define the evaluation metrics: False Positive Rate (FPR) and F1-score, comparing the proposed system against a baseline static threshold.  
* **Slide 12: Conclusion & Q\&A (1 min)**  
  * Summarize how the project transforms authentication from a rigid perimeter into a dynamic, behavioral defense layer.

## **16\. Final Quality Control Checklist**

| Rubric Requirement | Evidence Prepared | Location in Document |
| :---- | :---- | :---- |
| **Problem Understanding (4 Marks)** | Clear definition, workflow, real-world impact, and current challenges detailed. | Section 1 |
| **Literature Survey (4 Marks)** | 10 verified papers (2022-2026) analyzed for objective, method, and limits. | Section 2 & 3 |
| **Existing Work Analysis** | Comparison table of Number Matching, FIDO2, Rate Limiting, SIEM. | Section 4 |
| **Novelty & Research Gap (6 Marks)** | Defensible gaps identified; ML behavioral fusion proposed (not just UI changes). | Section 5 & 6 |
| **System Design & Methodology (4 Marks)** | Inputs, features, ML engine (Isolation Forest), risk scoring, and architecture flow. | Section 8 & 9 |
| **Project Planning (2 Marks)** | Module schedule, dataset strategy, and evaluation metrics defined. | Section 10, 12, 13 |
| **Presentation & Defense Prep** | Comprehensive viva Q\&A and 12-slide presentation structure provided. | Section 14 & 15 |

#### **Works cited**

> 1. ATT\&CK Technique T1621 \- Mappings Explorer, [https://center-for-threat-informed-defense.github.io/mappings-explorer/attack/attack-12.1/domain-enterprise/techniques/T1621/](https://center-for-threat-informed-defense.github.io/mappings-explorer/attack/attack-12.1/domain-enterprise/techniques/T1621/)  
> 2. How MFA Fatigue Attack Works and How to Fight Back, [https://www.prophetsecurity.ai/blog/what-is-mfa-fatigue-attack-mfa-bombing-best-practices](https://www.prophetsecurity.ai/blog/what-is-mfa-fatigue-attack-mfa-bombing-best-practices)  
> 3. Multi-Factor Authentication Request Generation, Technique T1621, [https://attack.mitre.org/techniques/T1621/](https://attack.mitre.org/techniques/T1621/)  
> 4. What Is MFA Fatigue? How MFA Bombing Attacks Work & Prevention, [https://www.miniorange.com/blog/mfa-fatigue/](https://www.miniorange.com/blog/mfa-fatigue/)  
> 5. T1621: Multi-Factor Authentication Request Generation, [https://mitre.ptsecurity.com/en-US/T1621](https://mitre.ptsecurity.com/en-US/T1621)  
> 6. MFA Fatigue Attacks: Detection, Prevention & Prompt Bombing, [https://www.loginradius.com/blog/identity/mfa-fatigue-attacks-prevention](https://www.loginradius.com/blog/identity/mfa-fatigue-attacks-prevention)  
> 7. "Decision Fatigue and Cybersecurity Behaviors: A Qualitative Study, [https://jisem-journal.com/index.php/journal/article/download/12613/5861/21211](https://jisem-journal.com/index.php/journal/article/download/12613/5861/21211)  
> 8. Scattered Spider \- CISA, [https://www.cisa.gov/sites/default/files/2023-11/aa23-320a\_scattered\_spider\_0.pdf](https://www.cisa.gov/sites/default/files/2023-11/aa23-320a_scattered_spider_0.pdf)  
> 9. MFA Request Generation \- Red Canary Threat Detection Report, [https://redcanary.com/threat-detection-report/techniques/mfa-request-generation/](https://redcanary.com/threat-detection-report/techniques/mfa-request-generation/)  
> 10. C0027, Campaign C0027 | MITRE ATT\&CK®, [https://attack.mitre.org/campaigns/C0027/](https://attack.mitre.org/campaigns/C0027/)  
> 11. What Is an MFA Fatigue Attack? | Examples & Prevention Tips, [https://sosafe-awareness.com/glossary/mfa-fatigue-attack/](https://sosafe-awareness.com/glossary/mfa-fatigue-attack/)  
> 12. Identity Is the New Perimeter: Why IAM Is the Frontline of Cybersecurity, [https://www.cyberdefensemagazine.com/identity-is-the-new-perimeter-why-iam-is-the-frontline-of-cybersecurity/](https://www.cyberdefensemagazine.com/identity-is-the-new-perimeter-why-iam-is-the-frontline-of-cybersecurity/)  
> 13. Implementing Phishing-Resistant MFA \- CISA, [https://www.cisa.gov/sites/default/files/publications/fact-sheet-implementing-phishing-resistant-mfa-508c.pdf](https://www.cisa.gov/sites/default/files/publications/fact-sheet-implementing-phishing-resistant-mfa-508c.pdf)  
> 14. SVR Cyber Actors Adapt Tactics for Initial Cloud Access \- CISA, [https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-057a](https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-057a)  
> 15. What Is an MFA Fatigue Attack? Meaning | Proofpoint AU, [https://www.proofpoint.com/au/threat-reference/mfa-fatigue-attack](https://www.proofpoint.com/au/threat-reference/mfa-fatigue-attack)  
> 16. MFA Fatigue Attacks: What They Are & How to Respond \- Rippling, [https://www.rippling.com/blog/mfa-fatigue](https://www.rippling.com/blog/mfa-fatigue)  
> 17. (PDF) AI-Based Detection of Account Takeover Attacks in Hotel, [https://www.researchgate.net/publication/412765477\_AI-Based\_Detection\_of\_Account\_Takeover\_Attacks\_in\_Hotel\_Reservation\_Platforms](https://www.researchgate.net/publication/412765477_AI-Based_Detection_of_Account_Takeover_Attacks_in_Hotel_Reservation_Platforms)  
> 18. Usability and Security Analysis of the Compare-and-Confirm Method, [https://par.nsf.gov/servlets/purl/10614810](https://par.nsf.gov/servlets/purl/10614810)  
> 19. Detecting MFA Fatigue and Adversary-in-the-Middle at Scale \- ijhes, [https://ijhes.com/index.php/ijhes/article/view/439](https://ijhes.com/index.php/ijhes/article/view/439)  
> 20. Integration of GenAI and Behavioral Analysis in an Authentication, [https://www.researchgate.net/publication/398932713\_Integration\_of\_GenAI\_and\_Behavioral\_Analysis\_in\_an\_Authentication\_System](https://www.researchgate.net/publication/398932713_Integration_of_GenAI_and_Behavioral_Analysis_in_an_Authentication_System)  
> 21. A Theoretical Framework for Decentralized Intrusion Detection in, [https://www.researchgate.net/publication/390975415\_A\_Theoretical\_Framework\_for\_Decentralized\_Intrusion\_Detection\_in\_Smart\_Networks\_using\_Blockchain\_and\_Machine\_Learning](https://www.researchgate.net/publication/390975415_A_Theoretical_Framework_for_Decentralized_Intrusion_Detection_in_Smart_Networks_using_Blockchain_and_Machine_Learning)  
> 22. Multi-Factor Authentication (MFA): Effectiveness Against Cyberattacks, [https://admin.mantechpublications.com/index.php/IJoCSDTCD/article/download/4027/2620](https://admin.mantechpublications.com/index.php/IJoCSDTCD/article/download/4027/2620)  
> 23. Artificial Intelligence for Real-Time Vulnerability Assessment in Hotel, [https://www.researchgate.net/publication/412399871\_Artificial\_Intelligence\_for\_Real-Time\_Vulnerability\_Assessment\_in\_Hotel\_Booking](https://www.researchgate.net/publication/412399871_Artificial_Intelligence_for_Real-Time_Vulnerability_Assessment_in_Hotel_Booking)  
> 24. Anomaly Detection for IoT Global Connectivity \- arXiv, [https://arxiv.org/html/2508.09660v1](https://arxiv.org/html/2508.09660v1)  
> 25. Multi-Factor Key Derivation Function (MFKDF) for Fast, Flexible, [https://www.usenix.org/system/files/sec23fall-prepub-451-nair.pdf](https://www.usenix.org/system/files/sec23fall-prepub-451-nair.pdf)  
> 26. Synthetic Data Generation in Cybersecurity: A Comparative Analysis, [https://arxiv.org/html/2410.16326v1](https://arxiv.org/html/2410.16326v1)  
> 27. MFA Fatigue Attack: How to Detect and Prevent It | Ping Identity, [https://www.pingidentity.com/en/resources/blog/post/mfa-bombing-dismantled.html](https://www.pingidentity.com/en/resources/blog/post/mfa-bombing-dismantled.html)  
> 28. How did a hacker bypass our multi-factor? \- Microsoft Q\&A, [https://learn.microsoft.com/en-us/answers/questions/5316432/how-did-a-hacker-bypass-our-multi-factor](https://learn.microsoft.com/en-us/answers/questions/5316432/how-did-a-hacker-bypass-our-multi-factor)  
> 29. Multi-factor authentication | IEEE Technology Navigator, [https://technav.ieee.org/topic/multi-factor-authentication/](https://technav.ieee.org/topic/multi-factor-authentication/)  
> 30. What is MFA Fatigue? | Security A-Z \- Pwned Labs, [https://pwnedlabs.io/glossary/what-is-mfa-fatigue](https://pwnedlabs.io/glossary/what-is-mfa-fatigue)  
> 31. Adaptive Authentication and API Security: Evaluating Multi-Factor, [https://www.researchgate.net/publication/413985438\_Adaptive\_Authentication\_and\_API\_Security\_Evaluating\_Multi-Factor\_Authentication\_in\_REST\_and\_SOAP-Based\_Distributed\_Systems](https://www.researchgate.net/publication/413985438_Adaptive_Authentication_and_API_Security_Evaluating_Multi-Factor_Authentication_in_REST_and_SOAP-Based_Distributed_Systems)  
> 32. The Mobile Paradox: How Interface Friction Can Improve 2FA Security, [https://www.computer.org/csdl/proceedings-article/icnc/2026/11416876/2eOZHv02G4g](https://www.computer.org/csdl/proceedings-article/icnc/2026/11416876/2eOZHv02G4g)  
> 33. Deep Learning for Anomaly Detection, [https://ff12.fastforwardlabs.com/](https://ff12.fastforwardlabs.com/)  
> 34. How To Use Machine Learning To Detect Zero-Day Attacks – ITU, [https://www.ituonline.com/blogs/how-to-use-machine-learning-to-detect-zero-day-attacks/](https://www.ituonline.com/blogs/how-to-use-machine-learning-to-detect-zero-day-attacks/)  
> 35. US11374952B1 \- Detecting anomalous events using autoencoders, [https://patents.google.com/patent/US11374952B1/en](https://patents.google.com/patent/US11374952B1/en)  
> 36. A Hybrid Framework for Robust Anomaly Detection, [https://www.ijcesen.com/index.php/ijcesen/article/download/1383/658/5015](https://www.ijcesen.com/index.php/ijcesen/article/download/1383/658/5015)  
> 37. MASTER'S THESIS, [https://www.diva-portal.org/smash/get/diva2:2067832/FULLTEXT02](https://www.diva-portal.org/smash/get/diva2:2067832/FULLTEXT02)

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACYAAAAXCAYAAABnGz2mAAACMklEQVR4Xu2WMUhVURjHv9Ag0SwlclDoSW0FDkHSEDg05JCKiA21ORTRFFGQc4O0iEVQCNEgNLS2VIMoiIigRNLUEkG0JAQFNVT//73fee9737vv8K76eG/wBz8e93z3nvedc79zzhXZp7G0wfuw3wcijKqXfMBzQB2Er+AqXIebcBK2lG4t4yB8BEd8wNAD210bn6Mz8JyLFemGL9XnsNPETsGP8K6UkreMwyew1bQdVfmHc/ArPGviFvb/Bvb5wBH4Dj5TOQrPVfgbnlcDfPatayNT6k14B/6U6olxoI/hPR9oysSYBJPhq2Id0CzYKTu/rQYuwhXYZdo8lyWeGGE/S5IONIEr4i+8FRqqEBLjqOzIHsB5c51FLYmxvrjIBnhxCL6G2/CMuSkLFvg/KU+Mxc7VW1EbjloSOwyXJb03yfKLNjAQgyuLiQ2rpAMuinYWoZbEQl/JIMPrWZDKLcDCumMNfoDHVVK3xPg+f8AX5oYsrklah/y11C2xY3BLGxjIogA/SfY2Ejq77to9eRLjtpRwA/6CF0KDoQDXJD0J/HES4GzzjIxRS2KhXLhtJHAWpuE3Ke1RE3AWvpf4GUk4W1yZ9jgiHDD9DP9IunC+63Xxzw0sK57LvT7AqRxSx+BJiScU4DazIfm+KrLgAPlmKhZh0ya2U/gKuTD8is0Dv+VYDv683TUnJO047G95uQIfyh7OloXfXfzg81tKjNPqUzGHdz3glpInMd6f95nG8R94hnMm3+JI5wAAAABJRU5ErkJggg==>

[image2]: <data:image/png;base64,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>

[image3]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABUAAAAZCAYAAADe1WXtAAAAeElEQVR4XmNgGAWjYMABNxB7AzEjugQlgAWIG4BYHE2cYuACxLnogpQCkNdLgdgTXQIGxIC4G4hnkYgXAPFrIJ4NxcIMSIAmhpILDIB4PhDLQDHFAGTINCDmR5egBJQBsSW6ICWAB4hboDTVADMQ86ILjoJRQEMAAAPgGuCoXQ7VAAAAAElFTkSuQmCC>

[image4]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIAAAAbCAYAAAA+nNxPAAAByElEQVR4Xu3WPyiFURgG8FcIMch/GfwXKQZJyoAMJBQGZbMwGRiMEovBYrSIkpRNUgZJBsWkLKJkQ0aLhOfpvKfOd+/n5g6++q7vqd9wz723e873nvecKxIlyr9NOtRCF+TFvBeqpMRCimEP5mASjmEe0lRosgw9zutCOIFOFYpwG7EC/c4Yq7ANA8o3mTCmypzxHKiR4EvJ39uEd5gS0yuNcAQlyjdspifV5owvwKkkbjQ+hFIoTwInwsklSj3cwxfcwRk0eD7hk2m4UUU6lg2HsG4/9EMKYATGkzAIufxygnChrMarmMWwOrM67vsQMmBfTCnJbqMKeBBzYgQdzmENliALeuERPmFUxYXbgiVkVcimD16g1RkLKk1itjTnZsPK89TaUXF9mzILYaM/Q7uyYaNfimlOlpI9Q7Gpgysxpf+tc6iSn8OHyOM39pDhPNgGxJbwhDfnm5jTyp5YlXArZuUtsKjjQaUarqHDGWMF2DMzyhPb6B9woLiwXViBC9iAZvuFAMOT7UHMfCZgC1bFHPfkidsf+Yp/Bez+42u/7RRU+NvdMCTefomLvQjdSzCUYdncSzC0GRZz4cUdZVGiRIkS5a/yDd7AWsAixDjXAAAAAElFTkSuQmCC>

[image5]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIAAAAbCAYAAAA+nNxPAAABkUlEQVR4Xu3WTSgFURgG4E9+IkSE7BBRKBtKtij5KxTFzlYKCyU77G3uztZOWYki3WJhYcnGUiJZWVqI93W+MXfO3HHZ3Ole562nO/fM7zdzzpkRcXH5tymGTuiCCmtdTiUvCumBQ1iENXjV3wKVEymFI0hCrbbtwBv0q5wIC+HTeIZ2bduADxhRkeHO1Aczlu6U7bIVjo8SXS6DE7iBehUK+9usmD5IrDrVO2x/bx0OT9gAjX/ACynkzhnCY7fBFtyKGTeRmYY76FVMBzxIhkeoqYFJCT/Fn4xCOXfOEO/Yq3AKA8HVfngnWemC1V4JF7ButceZJTG9Y0gFMgGP0GK18/8TTFnt2Qq7O2er1HfHuJiuvq8CU3DeFMKuk5TwW3MO7qHZak+XVrgWs/1vXUKTRIfvCb4zzsQfS14hB6pI278yCOdixoSXOjEn4iQQV/hJ8gK74l8wxwgL4U2mQDi9JWAPltUVjEm8nwE89wocw7z4nyibYq6Z0qZaTJ+kOAuwUwXDissuLi4uLi4uUfkEHUVSGA88wM0AAAAASUVORK5CYII=>

[image6]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIAAAAbCAYAAAA+nNxPAAABoklEQVR4Xu3WPyhFURwH8J9QhAj5k4FkEwZ/JiOTorApq5Iki5GiLCY2i0kGNlkwGAzCaiElGzbFgvh+O7/TO+/d5/bucrnvnW99hnte773z53fOuSI+PgWbUuiDAajM+CxRyYuBcAAnsAj78A6zUKQSkTo4hi59ZsdX4QuGVSLSC29wChXaNggfsKmyhrU4oZqc9nJol/iXkvthHaYl9d/9YsordCAc7ZPibNgswZmEbzROQiM0R9AAxfxyhMxJDqU1AzeqXtvK4EhCRq+phTGYjGBEUiWTS9rgDjbETBwFUgIHsKPsUrbAA0zp81+lWszptSK/DMCGZXEvZlXIZgheoMdpizvs+JaYsuIEsxyrVCB5MxBu9GcxpwLZcKNfidmc42L2DGWmA67hMYJzMXUfFnZ8QYIn17wKhDcnz2yeVvbEaoVb2IVuWNb2uMKOcxUuYdvBS5KTSmmxG/0TDhUHtgdrcCHmBzrtF2IKy/kVvjPwQmQFUVrc/VGj+Hpgl5LP2crp38VehO4lmMiwjNxLMLEZFXPhxf0u5ePj41PA+QGoVFgWfyWyIAAAAABJRU5ErkJggg==>