import type { InvenTreePluginContext } from '@inventreedb/ui';

import { WorkshopPage } from './Page';
import { WorkshopPartPanel } from './PartPanel';

/** The Workshop page, at /web/plugin/workshop/jobs */
export function renderWorkshopPage(context: InvenTreePluginContext) {
  return <WorkshopPage context={context} />;
}

/** The Workshop panel on a part page */
export function renderWorkshopPartPanel(context: InvenTreePluginContext) {
  return <WorkshopPartPanel context={context} />;
}
