/*
p = Ether(src='11:22:33:44:55:66', dst='aa:bb:cc:dd:ee:ff', type=0x88b5) / b'\x00\xc0' / (b'\xfe' * 32) / (b'\xab' * 12)
*/

/* TODO
- How the 6 byte egress TS is written into 8 byte field
- Change the TS offset in Control plane
- get TS7 from control plane
- Set port config in p4 file (?)
- Diffrent methods of injecting traffic
*/

#include <core.p4>
#include <tna.p4>

#define CPU_PORT 192
#define timestamp_t bit<48>

struct metadata_t {}
struct egress_metadata_t {}

header  ts_ctrl_h {
    bit<8> f1;
    bit<8> f2;
    bit<48> f3;
}

header ethernet_h {
    bit<48> dst_addr;
    bit<48> src_addr;
    bit<16> ether_type;
}

header sync_ctrl_h {
    bit<2> state;
    bit<5> pad_0;
    bit<9> port; // TODO: use port type

    //timestamp_t s1_egreess;
    //timestamp_t s2_ingress;
    //timestamp_t s2_egress;
    //timestamp_t s1_ingress;
}

header ts48_h {
    bit<16> pad;
    bit<48> ts;
}

header ts64_h {
    bit<64> ts;
}

struct header_t {
    ptp_metadata_t ts_ctrl;
    ethernet_h ethernet;
    sync_ctrl_h sync_ctrl;
    ts64_h s1_e;
    ts48_h s2_i;
    ts64_h s2_e;
    ts48_h s1_i;
}

/*
header ptp_metadata_t {
    bit<8> udp_cksum_byte_offset;       // Byte offset at which the egress MAC
                                        // needs to update the UDP checksum


    bit<8> cf_byte_offset;              // Byte offset at which the egress MAC
                                        // needs to re-insert
                                        // ptp_sync.correction field

    bit<48> updated_cf;                 // Updated correction field in ptp sync
                                        // message
}
*/

// ---------------------------------------------------------------------------
// Ingress parser
// ---------------------------------------------------------------------------
parser SwitchIngressParser(
        packet_in pkt,
        out header_t hdr,
        out metadata_t ig_md,
        out ingress_intrinsic_metadata_t ig_intr_md) {

    state start {
        pkt.extract(ig_intr_md);
        pkt.advance(PORT_METADATA_SIZE);
        transition parse_ethernet;
    }

    state parse_ethernet {
        pkt.extract(hdr.ethernet);
        transition select(hdr.ethernet.ether_type) {
            0x88b5: parse_sync_ctrl; // local experiemntal
            default: accept;
        }
    }

    state parse_sync_ctrl {
        pkt.extract(hdr.sync_ctrl);
        pkt.extract(hdr.s1_e);
        pkt.extract(hdr.s2_i);
        pkt.extract(hdr.s2_e);
        pkt.extract(hdr.s1_i);
        transition accept;
    }
}

control SwitchIngress(
        inout header_t hdr,
        inout metadata_t ig_md,
        in    ingress_intrinsic_metadata_t ig_intr_md,
        in    ingress_intrinsic_metadata_from_parser_t ig_prsr_md,
        inout ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md,
        inout ingress_intrinsic_metadata_for_tm_t ig_tm_md)
{

    action set_s1_ingress() {
        hdr.s1_i.ts = ig_intr_md.ingress_mac_tstamp;
        ig_tm_md.ucast_egress_port = CPU_PORT; // Send to CPU
    }

    action set_s2_ingress() {
        hdr.s2_i.ts = ig_intr_md.ingress_mac_tstamp;
        ig_tm_md.ucast_egress_port = ig_intr_md.ingress_port;  // Send back to SW1
    }

    action send_to_peer() {
        ig_tm_md.ucast_egress_port = hdr.sync_ctrl.port; // Send to Peer
    }

    table process_ts_pkt {
        key = {
            hdr.ethernet.ether_type : exact;
            hdr.sync_ctrl.state : exact;
        }
        actions = {
            set_s1_ingress;
            set_s2_ingress;
            send_to_peer;
            @defaultonly NoAction;
        }
        const default_action = NoAction();
        const entries = {
            (0x88b5, 0): send_to_peer(); // First time in source switch
            (0x88b5, 1): set_s2_ingress(); // In Peer switch
            (0x88b5, 2): set_s1_ingress(); // Back in source switch
        }
    }

    apply {
        if (hdr.sync_ctrl.isValid()) process_ts_pkt.apply();
    }
}

control SwitchIngressDeparser(
        packet_out pkt,
        inout header_t hdr,
        in metadata_t ig_md,
        in ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md) {
    apply {
         pkt.emit(hdr);
    }
}

parser SwitchEgressParser(
        packet_in pkt,
        out header_t hdr,
        out egress_metadata_t eg_md,
        out egress_intrinsic_metadata_t eg_intr_md) {

    state start {
        pkt.extract(eg_intr_md);
        transition parse_ethernet;
    }

    state parse_ethernet {
        pkt.extract(hdr.ethernet);
        transition select(hdr.ethernet.ether_type) {
            0x88b5: parse_sync_ctrl; // local experiemntal
            default: accept;
        }
    }

    state parse_sync_ctrl {
        pkt.extract(hdr.sync_ctrl);
        pkt.extract(hdr.s1_e);
        pkt.extract(hdr.s2_i);
        pkt.extract(hdr.s2_e);
        pkt.extract(hdr.s1_i);
        transition accept;
    }
}

control SwitchEgress(
        inout header_t hdr,
        inout egress_metadata_t eg_md,
        in egress_intrinsic_metadata_t eg_intr_md,
        in egress_intrinsic_metadata_from_parser_t eg_intr_from_prsr,
        inout egress_intrinsic_metadata_for_deparser_t eg_intr_md_for_dprsr,
        inout egress_intrinsic_metadata_for_output_port_t eg_intr_md_for_oport) {

    action set_s1_egress() {
        eg_intr_md_for_oport.capture_tstamp_on_tx = 1; // Disable TS7
        eg_intr_md_for_oport.update_delay_on_tx = 1; // Enable TS6
        hdr.s1_e.setInvalid(); // Remove placeholder
        hdr.ts_ctrl.setValid();
        hdr.ts_ctrl.udp_cksum_byte_offset = 8w0;
        hdr.ts_ctrl.cf_byte_offset = 8w16;
        hdr.ts_ctrl.updated_cf = 48w0;
        hdr.sync_ctrl.state = 1; // 0 => 1
    }

    action set_s2_egress() {
        eg_intr_md_for_oport.capture_tstamp_on_tx = 1; // Disable TS7
        eg_intr_md_for_oport.update_delay_on_tx = 1; // Enable TS6
        hdr.s2_e.setInvalid(); // Remove placeholder
        hdr.ts_ctrl.setValid();
        hdr.ts_ctrl.udp_cksum_byte_offset = 8w0;
        hdr.ts_ctrl.cf_byte_offset = 8w32;
        hdr.ts_ctrl.updated_cf = 48w0;
        hdr.sync_ctrl.state = 2; // 1 => 2
    }

    table process_ts_pkt {
        key = {
            hdr.ethernet.ether_type : exact;
            hdr.sync_ctrl.state : exact;
        }
        actions = {
            set_s1_egress;
            set_s2_egress;
            @defaultonly NoAction;
        }
        const default_action = NoAction();
        const entries = {
            (0x88b5, 0): set_s1_egress(); // First time in source switch
            (0x88b5, 1): set_s2_egress(); // In Peer switch
            // (0x0000, 2): send_digest(); // Back in source switch
        }
    }

    apply {
        if (hdr.sync_ctrl.isValid()) process_ts_pkt.apply();
    }
}

control SwitchEgressDeparser(
        packet_out pkt,
        inout header_t hdr,
        in egress_metadata_t eg_md,
        in egress_intrinsic_metadata_for_deparser_t eg_dprsr_md) {
    apply {
        pkt.emit(hdr);
    }
}

Pipeline(SwitchIngressParser(),
         SwitchIngress(),
         SwitchIngressDeparser(),
         SwitchEgressParser(),
         SwitchEgress(),
         SwitchEgressDeparser()) pipe;

Switch(pipe) main;
