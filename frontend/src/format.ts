import type { JobState, MachineKind } from './types';

const NO_API =
  'The Workshop plugin API was not found. Check that "Enable URL integration" is switched on in the InvenTree plugin settings.';

/**
 * Check that a response really came from the plugin API.
 *
 * With URL integration switched off, InvenTree answers unknown /plugin/
 * URLs with the web interface, so the request "succeeds" with a page of HTML.
 */
export function apiData<T>(response: any, field: string): T {
  const data = response?.data;

  if (!data || typeof data !== 'object' || !(field in data)) {
    throw Object.assign(new Error(NO_API), { noApi: true });
  }

  return data as T;
}

/** Turn an API error into a message for the user */
export function apiError(err: any, fallback: string): string {
  const status = err?.response?.status;
  const data = err?.response?.data;

  if (err?.noApi || (status === 404 && typeof data !== 'object')) {
    return NO_API;
  }

  if (status === 403) {
    return 'You do not have permission to do this.';
  }

  if (status === 413) {
    return 'The file is too big for the server to accept.';
  }

  if (data && typeof data === 'object' && !(data instanceof Blob)) {
    if (typeof data.detail === 'string') {
      return data.detail;
    }

    const messages: string[] = [];

    for (const value of Object.values(data)) {
      if (Array.isArray(value)) {
        messages.push(...value.map(String));
      } else if (typeof value === 'string') {
        messages.push(value);
      }
    }

    if (messages.length > 0) {
      return messages.join(' ');
    }
  }

  return `${fallback}${err?.message ? `: ${err.message}` : ''}`;
}

/** Messages for individual form fields, from a refused link */
export function fieldErrors(err: any): Record<string, string> {
  const errors = err?.response?.data?.errors;

  return errors && typeof errors === 'object' ? errors : {};
}

export function fmtQty(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '';
  }

  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** A quantity of material: up to four decimals, since a part may use 0.0125 of a sheet */
export function fmtMaterial(value: number | null | undefined, units?: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '';
  }

  const number = value.toLocaleString(undefined, { maximumFractionDigits: 4 });

  return units ? `${number} ${units}` : number;
}

export function plural(count: number, one: string, many?: string): string {
  return `${fmtQty(count)} ${count === 1 ? one : (many ?? `${one}s`)}`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) {
    return '';
  }

  const date = new Date(iso);

  if (Number.isNaN(date.getTime())) {
    return '';
  }

  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit'
  });
}

/** A date without a time (YYYY-MM-DD), shown as "23 Nov" */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) {
    return '';
  }

  const [year, month, day] = iso.slice(0, 10).split('-').map(Number);
  const date = new Date(year, (month || 1) - 1, day || 1);

  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

export function fmtBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || bytes <= 0) {
    return '';
  }

  if (bytes < 1024) {
    return `${bytes} B`;
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toLocaleString(undefined, { maximumFractionDigits: 0 })} kB`;
  }

  return `${(bytes / 1024 / 1024).toLocaleString(undefined, { maximumFractionDigits: 1 })} MB`;
}

export function runsFor(quantity: number, perRun: number): number {
  if (!(quantity > 0) || !(perRun > 0)) {
    return 0;
  }

  return Math.ceil(quantity / perRun - 1e-9);
}

/** Machine time: "25 min", "1 h 30 min" */
export function fmtMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !(minutes > 0)) {
    return '';
  }

  const whole = Math.max(1, Math.round(minutes));
  const hours = Math.floor(whole / 60);
  const rest = whole % 60;

  if (hours === 0) {
    return `${rest} min`;
  }

  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

export const KIND_NAME: Record<MachineKind, string> = {
  laser: 'Laser',
  cnc: 'CNC',
  other: 'Other'
};

export const KIND_COLOR: Record<MachineKind, string> = {
  laser: 'red',
  cnc: 'indigo',
  other: 'gray'
};

export const JOB_STATE: Record<JobState, { label: string; color: string; hint: string }> = {
  open: {
    label: 'To make',
    color: 'violet',
    hint: 'Take the files, set the machine up and run it. Then book what came out.'
  },
  partial: {
    label: 'Part made',
    color: 'orange',
    hint: 'Some parts are in stock. Make and book the rest, or close the job as it is.'
  },
  done: { label: 'Done', color: 'green', hint: 'The parts are in stock.' },
  cancelled: { label: 'Cancelled', color: 'gray', hint: 'The job was cancelled.' }
};
