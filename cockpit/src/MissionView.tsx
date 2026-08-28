import type { MissionEvent } from "../../contracts/events";
import { buildMissionPlan, type PlanNode } from "./missionPlan";

/** One node of the plan tree - a top-level stage or one of its children
 *  (an evidence lane, a licence gate). Rendered the same way regardless of
 *  depth; only top-level stages get children. */
function PlanNodeItem({ node }: { node: PlanNode }) {
  return (
    <li className={`plan-node plan-node--${node.status}`}>
      <span className="plan-node__status" aria-hidden="true" />
      <span className="plan-node__label">{node.label}</span>
      {node.detail && <span className="plan-node__detail">{node.detail}</span>}
      {node.children && (
        <ol className="plan-node__children">
          {node.children.map((child) => (
            <PlanNodeItem key={child.id} node={child} />
          ))}
        </ol>
      )}
    </li>
  );
}

/**
 * The mission view: the plan tree from §10's architecture diagram (message
 * -> evidence -> detonation -> verdict -> 4 licence gates -> complete),
 * expanding as matching events arrive (T-051). Evidence lanes and gate
 * slots are always shown - pending until their events land - so the shape
 * of the mission is visible from the first event, not just its history.
 */
export function MissionView({ events }: { events: MissionEvent[] }) {
  const plan = buildMissionPlan(events);
  return (
    <ol className="plan-tree">
      {plan.map((node) => (
        <PlanNodeItem key={node.id} node={node} />
      ))}
    </ol>
  );
}
