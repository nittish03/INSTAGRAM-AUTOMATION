export type User = {
  id: number;
  username: string;
  email: string;
  firstName: string;
  lastName: string;
  isStaff: boolean;
  isSuperuser: boolean;
};

export type DashboardStats = {
  totalLeads: number;
  pipelineTotal: number;
  connected: number;
  pending: number;
  failed: number;
  completed: number;
  actionsToday: number;
  actionsWeek: number;
  acceptanceRate: number;
  conversionRate: number;
  draftsAwaitingApproval: number;
};

export type DaemonStatus = {
  running: boolean;
  pid: number | null;
  startedAt: string;
};

export type DaemonLogsPayload = {
  exists: boolean;
  path: string;
  lines: string[];
  sizeBytes: number;
  modifiedAt: string;
};

export type Campaign = {
  id: number;
  name: string;
  isFreemium: boolean;
  actionFraction: number;
  bookingLink: string;
  objective: string;
  productDocs: string;
  users: { id: number; username: string }[];
};

export type Lead = {
  id: number;
  fullName: string;
  firstName: string;
  lastName: string;
  companyName: string;
  linkedinUrl: string;
  publicIdentifier: string;
  state: string;
  sheetExportedAt: string | null;
  updatedAt: string;
};

export type Deal = {
  id: number;
  state: string;
  closingReason: string;
  reason: string;
  connectAttempts: number;
  backoffHours: number;
  campaign: { id: number; name: string };
  lead: {
    id: number;
    name: string;
    publicIdentifier: string;
    linkedinUrl: string;
  };
  createdAt: string;
  updatedAt: string;
};

export type TaskItem = {
  id: number;
  taskType: string;
  status: string;
  scheduledAt: string;
  startedAt: string | null;
  endedAt: string | null;
  error: string;
  payload: Record<string, unknown>;
  dealId: number | null;
};

export type DraftMessage = {
  id: number;
  content: string;
  createdAt: string;
  campaign: string;
  campaignId: number | null;
  owner: string;
  leadName: string;
  leadPublicIdentifier: string;
  latestMessage: {
    content: string;
    createdAt: string;
    isOutgoing: boolean;
    senderLabel: string;
  } | null;
};

export type DraftRegenerationResponse = {
  status: string;
  changed: boolean;
  reason: string;
  oldContent: string;
  item: {
    id: number;
    content: string;
    createdAt: string;
    campaignId: number | null;
    latestMessage?: DraftMessage["latestMessage"];
  };
};

export type ActionLog = {
  id: number;
  actionType: string;
  status: string;
  targetName: string;
  targetPublicId: string;
  note: string;
  createdAt: string;
  campaign: { id: number; name: string };
  profile: { id: number; username: string; djangoUser: string };
};

export type LinkedInProfileItem = {
  id: number;
  userId: number;
  djangoUser: string;
  djangoEmail: string;
  linkedinUsername: string;
  active: boolean;
  subscribeNewsletter: boolean;
  newsletterProcessed: boolean;
  legalAccepted: boolean;
  connectDailyLimit: number;
  connectWeeklyLimit: number;
  followUpDailyLimit: number;
  hasCookies: boolean;
  createdAt: string | null;
};

export type LinkedInProfileCreatePayload = {
  linkedinUsername: string;
  linkedinPassword: string;
  active?: boolean;
  subscribeNewsletter?: boolean;
  connectDailyLimit?: number;
  connectWeeklyLimit?: number;
  followUpDailyLimit?: number;
};

export type SearchKeywordItem = {
  id: number;
  keyword: string;
  used: boolean;
  usedAt: string | null;
  campaign: { id: number; name: string };
};

export type SiteConfig = {
  llmProvider: string;
  aiModel: string;
  llmApiBase: string;
  azureDeployment: string;
  azureApiVersion: string;
  hasLlmApiKey: boolean;
  googleSheetSyncEnabled: boolean;
  googleSheetId: string;
  googleSheetTab: string;
  googleSheetSyncUserId: number | null;
  scope?: "user" | "global";
};

export type SiteConfigResponse = {
  config: SiteConfig;
  providerChoices: { value: string; label: string }[];
};

export type AnalyticsData = {
  rangeDays: number;
  daily: { date: string; connect: number; followUp: number }[];
  dealStates: { state: string; count: number }[];
  taskStates: { status: string; count: number }[];
  topCampaigns: { id: number; name: string; count: number }[];
};

export type GoogleStatus = {
  connected: boolean;
  email: string;
  scopes: string[];
  /** Redirect URI registered with Google – display so user can match Google Console exactly. */
  redirectUri?: string;
};

export type GoogleSheetItem = {
  id: string;
  name: string;
  modifiedTime: string;
  webViewLink: string;
  isConfiguredSheet?: boolean;
};

export type GoogleSheetMeta = {
  spreadsheetId: string;
  title: string;
  spreadsheetUrl: string;
  sheetTabs: string[];
};

export type GoogleGridCellStyle = {
  bg?: Record<string, number>;
  text?: Record<string, number>;
  bold?: boolean;
  italic?: boolean;
  align?: string;
  hyperlink?: string;
};

export type MessagingDiagnostics = {
  connectedDeals: number;
  draftsTotal: number;
  draftsUnapproved: number;
  pendingFollowupTasks: number;
  failedFollowupTasks: number;
  pendingSendMessageTasks: number;
  llmConfigured: boolean;
  lastFailedFollowup: {
    taskId: number;
    endedAt: string | null;
    error: string;
  } | null;
  leadsWithoutDraft: {
    leadId: number;
    publicIdentifier: string;
    fullName: string;
    campaign: string;
  }[];
};

export type WorkbenchSummary = {
  stats: {
    connectedDeals: number;
    draftsAwaitingApproval: number;
    failedTasks: number;
    pendingTasks: number;
    stalePendingDeals: number;
    connectedWithoutExport: number;
    connectedAwaitingVerification: number;
    connectedWithoutFollowup: number;
    actions24h: number;
  };
  inbox: { key: string; count: number; priority: "high" | "medium" | "low" }[];
};

export type LeadInsights = {
  leadId: number;
  qualityScore: number;
  reasons: string[];
  conflicts: string[];
  nextAction: string;
  dealState: string;
};

export type TimelineEvent = {
  kind: "deal" | "task" | "action" | "message" | "export" | "outreach_event";
  at: string;
  title: string;
  detail: string;
  campaign: string;
};

export type CampaignHealthItem = {
  campaignId: number;
  campaignName: string;
  totalDeals: number;
  connected: number;
  completed: number;
  failed: number;
  pending: number;
  draftsAwaitingApproval: number;
  taskFailures: number;
  followupsLogged: number;
  acceptanceRate: number;
  conversionRate: number;
  healthScore: number;
};

export type RecoveryItem = {
  taskId: number;
  taskType: string;
  status: string;
  error: string;
  dealId: number | null;
  leadPublicIdentifier: string;
  campaignId: number | null;
  scheduledAt: string;
  endedAt: string | null;
};

export type ExportPreviewItem = {
  leadId: number;
  fullName: string;
  publicIdentifier: string;
  campaign: string;
  connectedAt: string;
  sheetExportedAt: string | null;
  reason?: string;
};

export type FollowupSuggestion = {
  leadId: number;
  dealId: number;
  campaignId: number;
  campaign: string;
  fullName: string;
  publicIdentifier: string;
  action: string;
  rationale: string;
};

export type SafeModeSettings = {
  enabled: boolean;
  globalPauseOutreach: boolean;
  pauseNewConnectionInvites: boolean;
  maxBulkApprove: number;
  maxBulkExport: number;
};
