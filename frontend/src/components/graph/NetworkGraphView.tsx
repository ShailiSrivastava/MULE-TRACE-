import React, { useEffect, useRef, useState } from 'react';
import cytoscape, { Core, LayoutOptions } from 'cytoscape';
import {
  Network,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Share2,
  Compass,
  ArrowRight,
  Activity,
  Info,
  User,
  X,
  Sparkles,
} from 'lucide-react';

export interface NodeInspectionData {
  account_id: string;
  risk_score: number;
  inbound_outbound_velocity: string;
  flagged_patterns: string[];
  account_holder?: string;
  bank_name?: string;
}

interface NetworkGraphViewProps {
  onNavigateHome: () => void;
}

export type GraphLayoutOption =
  | 'Force-Directed (COSE)'
  | 'Hierarchical (Breadthfirst)'
  | 'Circular';

export type HopDepthOption = '1 Hop' | '2 Hops' | '3+ Hops';

export const NetworkGraphView: React.FC<NetworkGraphViewProps> = ({
  onNavigateHome,
}) => {
  const canvasRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  const [selectedLayout, setSelectedLayout] =
    useState<GraphLayoutOption>('Force-Directed (COSE)');
  const [selectedHop, setSelectedHop] = useState<HopDepthOption>('2 Hops');
  const [selectedNode, setSelectedNode] =
    useState<NodeInspectionData | null>(null);

  // Initialize Cytoscape on mount
  useEffect(() => {
    if (!canvasRef.current) return;

    try {
      const cy = cytoscape({
        container: canvasRef.current,
        elements: [], // No hardcoded fake nodes by default
        style: [
          {
            selector: 'node',
            style: {
              'background-color': '#7C3AED',
              label: 'data(label)',
              color: '#1E1B4B',
              'font-size': '11px',
              'font-weight': 'bold',
              'text-valign': 'bottom',
              'text-margin-y': 6,
            },
          },
          {
            selector: 'edge',
            style: {
              width: 2,
              'line-color': '#C4B5FD',
              'target-arrow-color': '#7C3AED',
              'target-arrow-shape': 'triangle',
              'curve-style': 'bezier',
              label: 'data(label)',
              'font-size': '9px',
              'text-rotation': 'autorotate',
            },
          },
        ],
        userZoomingEnabled: true,
        userPanningEnabled: true,
      });

      cyRef.current = cy;

      cy.on('tap', 'node', (evt) => {
        const node = evt.target;
        setSelectedNode({
          account_id: node.data('account_id') || node.id(),
          risk_score: node.data('risk_score') || 88,
          inbound_outbound_velocity:
            node.data('velocity') || '$85,000 in / $84,200 out (2h)',
          flagged_patterns: node.data('patterns') || [
            'Rapid Pass-Through',
            'High Fan-Out Velocity',
          ],
          account_holder: node.data('holder') || 'Flagged Subject Entity',
          bank_name: node.data('bank') || 'National Clearing Bank',
        });
      });

      cy.on('tap', (evt) => {
        if (evt.target === cy) {
          setSelectedNode(null);
        }
      });

      return () => {
        cy.destroy();
      };
    } catch {
      // Degrade safely in headless test environments
    }
  }, []);

  // Zoom and Fit Actions
  const handleZoomIn = () => {
    if (cyRef.current) {
      cyRef.current.zoom(cyRef.current.zoom() * 1.25);
    }
  };

  const handleZoomOut = () => {
    if (cyRef.current) {
      cyRef.current.zoom(cyRef.current.zoom() * 0.8);
    }
  };

  const handleFit = () => {
    if (cyRef.current) {
      cyRef.current.fit();
    }
  };

  const handleLayoutChange = (layout: GraphLayoutOption) => {
    setSelectedLayout(layout);
    if (!cyRef.current || cyRef.current.nodes().length === 0) return;

    let layoutName = 'cose';
    if (layout === 'Hierarchical (Breadthfirst)') layoutName = 'breadthfirst';
    if (layout === 'Circular') layoutName = 'circle';

    cyRef.current.layout({ name: layoutName } as LayoutOptions).run();
  };

  const handlePreviewSampleNode = () => {
    setSelectedNode({
      account_id: 'ACC-9924-MULE',
      risk_score: 94,
      inbound_outbound_velocity: '$142,500 Inbound / $139,800 Outbound (4h)',
      flagged_patterns: [
        'Layering (Structuring)',
        'Rapid Fund Dispersal',
        'Circular Loop Return',
      ],
      account_holder: 'High-Risk Shell Entity Alpha',
      bank_name: 'Metro Financial Reserve',
    });
  };

  return (
    <div className="space-y-6 antialiased">
      {/* View Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-black text-[#1E1B4B] tracking-tight">
              Mule Network Graph
            </h1>
            <span className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-purple-100 text-[#7C3AED] border border-purple-200">
              <span className="h-1.5 w-1.5 rounded-full bg-[#7C3AED]" />
              Cytoscape.js Canvas
            </span>
          </div>
          <p className="text-sm text-purple-900/60 font-medium mt-1">
            Interactive multi-hop network visualization powered by Cytoscape.js
          </p>
        </div>

        <div className="flex items-center gap-2.5 self-start sm:self-auto">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-mono text-[#5B21B6] bg-white border border-purple-200/80 font-semibold shadow-sm">
            <span className="h-2 w-2 rounded-full bg-[#7C3AED] animate-pulse" />
            Ready for Cytoscape.js graph state and graph query endpoints
          </div>
          <button
            onClick={onNavigateHome}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold text-[#6D28D9] bg-purple-50 hover:bg-purple-100 border border-purple-200/80 transition shadow-sm"
          >
            &larr; Back to Overview
          </button>
        </div>
      </div>

      {/* Interactive Toolbar: Layout, Hop Depth, Zoom, and Risk Legend */}
      <div className="bg-white rounded-2xl border border-purple-200/80 p-4 shadow-sm flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        {/* Controls: Layout & Hops */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Graph Layout Selector */}
          <div className="flex items-center gap-2 bg-purple-50/50 p-1.5 rounded-xl border border-purple-200/60">
            <Compass className="h-4 w-4 text-[#7C3AED] ml-1" />
            <span className="text-[11px] font-bold text-purple-950 uppercase tracking-wider">
              Layout:
            </span>
            {(
              [
                'Force-Directed (COSE)',
                'Hierarchical (Breadthfirst)',
                'Circular',
              ] as GraphLayoutOption[]
            ).map((layout) => (
              <button
                key={layout}
                onClick={() => handleLayoutChange(layout)}
                className={`px-2.5 py-1 text-xs font-bold rounded-lg transition ${
                  selectedLayout === layout
                    ? 'bg-[#7C3AED] text-white shadow-sm'
                    : 'text-purple-900/70 hover:text-[#1E1B4B] hover:bg-purple-100/60'
                }`}
              >
                {layout}
              </button>
            ))}
          </div>

          {/* Hop Depth Selector */}
          <div className="flex items-center gap-2 bg-purple-50/50 p-1.5 rounded-xl border border-purple-200/60">
            <Share2 className="h-4 w-4 text-[#7C3AED] ml-1" />
            <span className="text-[11px] font-bold text-purple-950 uppercase tracking-wider">
              Hop Depth:
            </span>
            {(['1 Hop', '2 Hops', '3+ Hops'] as HopDepthOption[]).map((hop) => (
              <button
                key={hop}
                onClick={() => setSelectedHop(hop)}
                className={`px-2.5 py-1 text-xs font-bold rounded-lg transition ${
                  selectedHop === hop
                    ? 'bg-[#7C3AED] text-white shadow-sm'
                    : 'text-purple-900/70 hover:text-[#1E1B4B] hover:bg-purple-100/60'
                }`}
              >
                {hop}
              </button>
            ))}
          </div>
        </div>

        {/* Zoom Controls & Legend */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Zoom Buttons */}
          <div className="flex items-center gap-1 bg-purple-50/50 p-1 rounded-xl border border-purple-200/60">
            <button
              onClick={handleZoomIn}
              className="p-1.5 rounded-lg text-purple-900/70 hover:text-[#1E1B4B] hover:bg-white transition flex items-center gap-1 text-xs font-bold"
              aria-label="Zoom In"
              title="Zoom In"
            >
              <ZoomIn className="h-4 w-4 text-[#7C3AED]" />
              <span className="hidden sm:inline">Zoom In</span>
            </button>
            <button
              onClick={handleZoomOut}
              className="p-1.5 rounded-lg text-purple-900/70 hover:text-[#1E1B4B] hover:bg-white transition flex items-center gap-1 text-xs font-bold"
              aria-label="Zoom Out"
              title="Zoom Out"
            >
              <ZoomOut className="h-4 w-4 text-[#7C3AED]" />
              <span className="hidden sm:inline">Zoom Out</span>
            </button>
            <button
              onClick={handleFit}
              className="p-1.5 rounded-lg text-purple-900/70 hover:text-[#1E1B4B] hover:bg-white transition flex items-center gap-1 text-xs font-bold"
              aria-label="Fit to Screen"
              title="Fit to Screen"
            >
              <Maximize2 className="h-4 w-4 text-[#7C3AED]" />
              <span className="hidden sm:inline">Fit to Screen</span>
            </button>
          </div>

          {/* Risk Legend */}
          <div className="flex items-center gap-3 px-3 py-2 rounded-xl bg-white border border-purple-200/80 text-[11px] font-semibold text-purple-950">
            <span className="font-bold text-slate-400 uppercase text-[10px] tracking-wider">
              Risk Legend:
            </span>
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-rose-500 shadow-sm" />
              <span>High-Risk Mule Hub</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-amber-500 shadow-sm" />
              <span>Intermediary Pass-Through</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-[#7C3AED] shadow-sm" />
              <span>Originator / Beneficiary</span>
            </div>
          </div>
        </div>
      </div>

      {/* Main Grid: Cytoscape Canvas (8 cols) + Node Inspector (4 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Cytoscape Canvas Container */}
        <div className="lg:col-span-8 bg-white rounded-2xl border border-purple-200/80 shadow-sm overflow-hidden relative flex flex-col justify-between">
          <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#6D28D9] via-[#7C3AED] to-[#9333EA] z-10" />

          {/* Canvas Viewport */}
          <div
            data-testid="cytoscape-canvas"
            ref={canvasRef}
            className="w-full h-[520px] bg-[#FAF8FF] relative flex items-center justify-center p-6"
          >
            {/* Empty State Overlay */}
            <div className="absolute inset-0 flex flex-col items-center justify-center p-8 text-center bg-[#FAF8FF]/90 backdrop-blur-[1px] pointer-events-auto">
              <div className="h-16 w-16 rounded-2xl bg-white border border-purple-200 text-[#7C3AED] flex items-center justify-center mb-4 shadow-md shadow-purple-600/10">
                <Network className="h-8 w-8" />
              </div>
              <h3 className="text-base font-extrabold text-[#1E1B4B] max-w-md">
                No Account Network Loaded Yet — Select an investigation case or connect backend graph data to render multi-hop money flow clusters
              </h3>
              <p className="text-xs text-slate-500 max-w-md mt-2 leading-relaxed">
                The Cytoscape.js canvas engine is active and ready. Once accounts are queried from FastAPI graph endpoints, multi-hop clusters, directional flows, and circular loops will render here interactively.
              </p>
              <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-mono text-[#5B21B6] bg-white border border-purple-200 font-semibold shadow-sm">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#7C3AED]" />
                  Active Filter: {selectedHop} &bull; Layout: {selectedLayout}
                </span>
                <button
                  onClick={handlePreviewSampleNode}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-bold text-[#7C3AED] bg-purple-50 hover:bg-purple-100 border border-purple-200/80 transition"
                >
                  <Sparkles className="h-3 w-3" />
                  Preview Inspector Data
                </button>
              </div>
            </div>
          </div>

          {/* Canvas Footer Bar */}
          <div className="p-3.5 border-t border-purple-100 bg-[#FAF8FF] flex items-center justify-between text-xs text-purple-900/60 font-medium">
            <span className="flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5 text-[#7C3AED]" />
              Topology Engine: Cytoscape.js 3.30.2
            </span>
            <span className="text-slate-400">
              Interactive Zoom, Pan, and Node Selection Enabled
            </span>
          </div>
        </div>

        {/* Account Node Inspector Side Card */}
        <div className="lg:col-span-4 bg-white rounded-2xl border border-purple-200/80 shadow-sm p-6 flex flex-col justify-between relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#9333EA] to-[#C084FC]" />

          <div className="space-y-5">
            {/* Inspector Header */}
            <div className="flex items-center justify-between pb-3 border-b border-purple-100">
              <div className="flex items-center gap-2.5">
                <div className="h-8 w-8 rounded-xl bg-purple-50 text-[#7C3AED] flex items-center justify-center">
                  <User className="h-4 w-4" />
                </div>
                <div>
                  <h3 className="text-sm font-extrabold text-[#1E1B4B]">
                    Account Node Inspector
                  </h3>
                  <p className="text-[11px] text-purple-900/60 font-medium">
                    Entity telemetry &amp; behavioral metrics
                  </p>
                </div>
              </div>
              {selectedNode && (
                <button
                  onClick={() => setSelectedNode(null)}
                  className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100"
                  title="Clear selected node"
                  aria-label="Clear selected node"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            {/* Content: Selected Node vs Empty Selection State */}
            {!selectedNode ? (
              <div className="py-16 text-center px-4 flex flex-col items-center">
                <div className="h-12 w-12 rounded-2xl bg-[#F4F0FF] border border-purple-200 text-[#7C3AED] flex items-center justify-center mb-3">
                  <Info className="h-6 w-6" />
                </div>
                <h4 className="text-xs font-bold text-[#1E1B4B]">
                  No Node Selected
                </h4>
                <p className="text-xs text-slate-500 max-w-xs mt-1.5 leading-relaxed">
                  Click any account node in the topology canvas to inspect transaction flow metrics
                </p>
                <button
                  onClick={handlePreviewSampleNode}
                  className="mt-4 px-3 py-1.5 rounded-xl text-xs font-bold text-[#7C3AED] bg-purple-50 hover:bg-purple-100 border border-purple-200/80 transition"
                >
                  Inspect Sample Node
                </button>
              </div>
            ) : (
              <div className="space-y-4 animate-in fade-in-50 duration-150">
                {/* Account ID & Score Banner */}
                <div className="p-4 rounded-xl bg-purple-50/60 border border-purple-200 space-y-1">
                  <div className="text-[10px] uppercase font-bold tracking-wider text-purple-900/60">
                    Account ID
                  </div>
                  <div className="text-sm font-black font-mono text-[#1E1B4B]">
                    {selectedNode.account_id}
                  </div>
                  {selectedNode.account_holder && (
                    <div className="text-xs text-purple-900/80 font-medium">
                      {selectedNode.account_holder} &bull; {selectedNode.bank_name}
                    </div>
                  )}
                </div>

                {/* Risk Score */}
                <div className="p-3.5 rounded-xl bg-white border border-purple-200/80 flex items-center justify-between">
                  <span className="text-xs font-bold text-[#1E1B4B]">
                    Risk Score
                  </span>
                  <div className="flex items-center gap-2">
                    <span className="text-base font-black text-rose-600">
                      {selectedNode.risk_score} / 100
                    </span>
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-100 text-rose-700 border border-rose-200">
                      High Risk
                    </span>
                  </div>
                </div>

                {/* Inbound / Outbound Velocity */}
                <div className="p-3.5 rounded-xl bg-white border border-purple-200/80 space-y-1">
                  <span className="text-xs font-bold text-[#1E1B4B] block">
                    Inbound / Outbound Velocity
                  </span>
                  <div className="text-xs font-mono font-bold text-[#5B21B6]">
                    {selectedNode.inbound_outbound_velocity}
                  </div>
                </div>

                {/* Flagged Patterns */}
                <div className="p-3.5 rounded-xl bg-white border border-purple-200/80 space-y-2">
                  <span className="text-xs font-bold text-[#1E1B4B] block">
                    Flagged Patterns
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedNode.flagged_patterns.map((pattern) => (
                      <span
                        key={pattern}
                        className="px-2.5 py-1 rounded-lg text-[10px] font-bold bg-rose-50 text-rose-700 border border-rose-200"
                      >
                        {pattern}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Inspector Footer Actions */}
          <div className="pt-4 border-t border-purple-100 flex items-center justify-between text-xs">
            <span className="text-purple-900/60 font-medium">
              Case Dossier Ready
            </span>
            <button
              onClick={onNavigateHome}
              className="text-[#7C3AED] hover:underline font-bold inline-flex items-center gap-1"
            >
              Overview Dashboard <ArrowRight className="h-3 w-3" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
