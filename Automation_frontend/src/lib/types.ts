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

export type Campaign = {
  id: number;
  name: string;
  isFreemium: boolean;
  actionFraction: number;
  bookingLink: string;
  objective: string;
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
  lead: { id: number; name: string; publicIdentifier: string; linkedinUrl: string };
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
};

export type GoogleSheetItem = {
  id: string;
  name: string;
  modifiedTime: string;
  webViewLink: string;
  isConfiguredSheet?: boolean;
};

export type MessagingDiagnostics = {
  connectedDeals: number;
  draftsTotal: number;
  draftsUnapproved: number;
  pendingFollowupTasks: number;
  failedFollowupTasks: number;
  pendingSendMessageTasks: number;
  llmConfigured: boolean;
  lastFailedFollowup: { taskId: number; endedAt: string | null; error: string } | null;
  leadsWithoutDraft: { leadId: number; publicIdentifier: string; fullName: string; campaign: string }[];
};
