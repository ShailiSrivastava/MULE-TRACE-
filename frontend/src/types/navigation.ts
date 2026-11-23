export type NavTabId =
  | 'overview'
  | 'transactions'
  | 'graph'
  | 'alerts'
  | 'cases'
  | 'risk'
  | 'reports';

export interface NavItem {
  id: NavTabId;
  label: string;
  badge?: string;
}
