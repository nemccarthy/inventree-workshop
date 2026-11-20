export interface Permissions {
  view: boolean;
  link: boolean;
  make: boolean;
  manage: boolean;
}

export type MachineKind = 'laser' | 'cnc' | 'other';

/** A machine of the workshop */
export interface Machine {
  id: number;
  name: string;
  kind: MachineKind;
  notes: string;
  kind_name?: string;
  /** Number of parts linked to it (only where the list is managed) */
  parts?: number;
}

export interface PartLabel {
  pk: number;
  name: string;
  ipn: string;
  description: string;
  units: string;
  active: boolean;
  assembly: boolean;
  trackable: boolean;
  minimum_stock: number;
  default_location: number | null;
}

/** Something a file does, shown as a badge: "Cut × 20" with its settings, or a tool */
export interface Operation {
  label: string;
  detail: string;
  tone: 'cut' | 'other';
}

/** What a file says about itself, whatever kind of file it is */
export interface FileSummary {
  recognised: boolean;
  /** 'xcs', 'gcode' or '' for any other file */
  kind: string;
  kind_name: string;
  size: number;
  facts: string[];
  operations: Operation[];
  notes: string[];
  /** A guess at the parts one run gives, from the file */
  parts_hint: number | null;
  parts_hint_text: string;
  /** Running time the file itself gives, in minutes */
  minutes_hint: number | null;
  has_cover: boolean;
}

/** A file attached to a part, read */
export interface FileDetail {
  attachment: number;
  filename: string;
  file_hash?: string;
  file_size?: number;
  missing: boolean;
  summary: FileSummary;
}

/** A file attached to a part, as listed */
export interface AttachedFile {
  attachment: number;
  filename: string;
  file_size: number;
  comment: string;
  uploaded: string | null;
  uploaded_by: string | null;
  kind: string;
  kind_name: string;
  linked: boolean;
}

/** A file of a link, in the order it is used */
export interface LinkFile {
  attachment: number;
  filename: string;
  label: string;
  file_hash: string | null;
  file_size: number | null;
  summary: FileSummary;
  missing: boolean;
  changed: boolean;
}

export interface Link {
  machine: number;
  machine_name: string | null;
  machine_kind: MachineKind | null;
  machine_notes: string;
  machine_missing: boolean;
  files: LinkFile[];
  parts_per_run: number;
  /** Machine time of one run, in minutes */
  run_minutes: number | null;
  restock_to: number | null;
  destination: number | null;
  destination_name: string | null;
  setup_notes: string;
  file_missing: boolean;
  file_changed: boolean;
}

/** A line of the bill of materials of a part */
export interface Material {
  part: number;
  name: string;
  ipn: string;
  units: string;
  per_part: number;
  consumable: boolean;
  taken: boolean;
}

export interface Numbers {
  stock: number;
  incoming: number;
  incoming_jobs: number;
  demand: number;
  demand_builds: { pk: number; reference: string; quantity: number }[];
  minimum: number;
}

export interface Suggestion {
  runs: number;
  quantity: number;
  reason: 'low_stock' | 'build_demand' | null;
  projected: number;
  floor: number;
  target: number;
  shortfall: number;
}

export type JobState = 'open' | 'partial' | 'done' | 'cancelled';

export interface JobSummary {
  state: JobState;
  remaining: number;
  runs_planned: number;
  runs_done: number;
  runs_left: number;
  rejected: number;
  can_book: boolean;
  can_close: boolean;
  can_cancel: boolean;
}

/** A material of a job: a line of its build order which takes stock */
export interface JobMaterial {
  line: number;
  part: number;
  name: string;
  ipn: string;
  units: string;
  per_part: number;
  per_run: number;
  required: number;
  consumed: number;
  in_stock: number;
}

export interface Booking {
  good: number;
  runs: number;
  by: string | null;
  at: string;
  location: number | null;
  material: { part: number; name: string; units: string; quantity: number }[];
  notes: string;
}

/** A file of a job, as it was when the job was raised */
export interface JobFile {
  attachment: number;
  filename: string | null;
  label: string;
  file_hash: string | null;
}

export interface Job {
  build: number;
  reference: string;
  title: string;
  part: number;
  part_name: string;
  part_ipn: string;
  quantity: number;
  completed: number;
  build_status: number;
  created: string | null;
  target_date: string | null;
  issued_by: string | null;
  destination: number | null;
  destination_name: string | null;
  source: string;
  machine: { id: number; name: string; kind: MachineKind | null } | null;
  files: JobFile[];
  parts_per_run: number;
  run_minutes: number | null;
  runs: number | null;
  notes: string;
  bookings: Booking[];
  material: JobMaterial[];
  summary: JobSummary;
}

export interface PartData {
  part: PartLabel;
  link: Link | null;
  materials: Material[];
  numbers: Numbers;
  suggestion: Suggestion | null;
  jobs: Job[];
  history: Job[];
  machines: Machine[];
  include_pending: boolean;
  permissions: Permissions;
}

export interface OverviewPart {
  part: PartLabel;
  link: Link;
  numbers: Numbers;
  suggestion: Suggestion;
  open_jobs: number;
}

export interface OverviewData {
  machines: Machine[];
  parts: OverviewPart[];
  jobs: Job[];
  history: Job[];
  include_pending: boolean;
  permissions: Permissions;
}
