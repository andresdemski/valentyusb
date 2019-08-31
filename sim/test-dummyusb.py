# Tests for the Fomu Tri-Endpoint
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, NullTrigger, Timer
from cocotb.result import TestFailure, TestSuccess, ReturnValue

from valentyusb.usbcore.utils.packet import *
from valentyusb.usbcore.endpoint import *
from valentyusb.usbcore.pid import *
from valentyusb.usbcore.utils.pprint import pp_packet

from wishbone import WishboneMaster, WBOp

from usbtest import UsbTest
import logging
import csv

@cocotb.test()
def test_control_setup(dut):
    harness = UsbTest(dut)
    yield harness.reset()
    # yield harness.connect()
    #   012345   0123
    # 0b011100 0b1000
    yield harness.transaction_setup(0,  [0x00, 0x05, 28, 0x00, 0x00, 0x00, 0x00, 0x00])
    yield harness.transaction_setup(28, [0x80, 0x06, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00])

@cocotb.test()
def test_control_transfer_in(dut):
    harness = UsbTest(dut)
    yield harness.reset()

    yield harness.connect()
    yield harness.write(harness.csrs['usb_address'], 20)
    yield harness.control_transfer_in(
        20,
        # Get descriptor, Index 0, Type 03, LangId 0000, wLength 10?
        [0x80, 0x06, 0x00, 0x06, 0x00, 0x00, 0x0A, 0x00],
        # 12 byte descriptor, max packet size 8 bytes
        [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
            0x08, 0x09, 0x0A, 0x0B],
    )

@cocotb.test()
def test_sof_stuffing(dut):
    harness = UsbTest(dut)
    yield harness.reset()

    yield harness.connect()
    yield harness.host_send_sof(0x04ff)
    yield harness.host_send_sof(0x0512)
    yield harness.host_send_sof(0x06e1)
    yield harness.host_send_sof(0x0519)

@cocotb.test()
def test_sof_is_ignored(dut):
    harness = UsbTest(dut)
    yield harness.reset()
    yield harness.connect()

    addr = 0x20
    epaddr_out = EndpointType.epaddr(0, EndpointType.OUT)
    epaddr_in = EndpointType.epaddr(0, EndpointType.IN)
    yield harness.write(harness.csrs['usb_address'], addr)

    data = [0, 1, 8, 0, 4, 3, 0, 0]
    @cocotb.coroutine
    def send_setup_and_sof():
        # Send SOF packet
        yield harness.host_send_sof(2)

        # Setup stage
        # ------------------------------------------
        # Send SETUP packet
        yield harness.host_send_token_packet(PID.SETUP, addr, EndpointType.epnum(epaddr_out))

        # Send another SOF packet
        yield harness.host_send_sof(3)

        # Data stage
        # ------------------------------------------
        # Send DATA packet
        yield harness.host_send_data_packet(PID.DATA1, data)
        yield harness.host_expect_ack()

        # Send another SOF packet
        yield harness.host_send_sof(4)

    # Indicate that we're ready to receive data to EP0
    # harness.write(harness.csrs['usb_epin_epno'], 0)

    xmit = cocotb.fork(send_setup_and_sof())
    yield harness.expect_setup(epaddr_out, data)
    yield xmit.join()

    # # Status stage
    # # ------------------------------------------
    yield harness.set_response(epaddr_out, EndpointResponse.ACK)
    yield harness.transaction_status_out(addr, epaddr_out)

@cocotb.test()
def test_control_setup_clears_stall(dut):
    harness = UsbTest(dut)
    yield harness.reset()
    yield harness.connect()

    addr = 28
    epaddr_out = EndpointType.epaddr(0, EndpointType.OUT)
    yield harness.write(harness.csrs['usb_address'], addr)

    d = [0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0, 0]

    # Send the data -- just to ensure that things are working
    yield harness.transaction_data_out(addr, epaddr_out, d)

    # Send it again to ensure we can re-queue things.
    yield harness.transaction_data_out(addr, epaddr_out, d)

    # STALL the endpoint now
    yield harness.write(harness.csrs['usb_enable_out0'], 0)
    yield harness.write(harness.csrs['usb_enable_out1'], 0)
    yield harness.write(harness.csrs['usb_enable_in0'], 0)
    yield harness.write(harness.csrs['usb_enable_in1'], 0)

    # Do another receive, which should fail
    yield harness.transaction_data_out(addr, epaddr_out, d, expected=PID.STALL)

    # Do a SETUP, which should pass
    yield harness.write(harness.csrs['usb_enable_out0'], 1)
    yield harness.control_transfer_out(addr, d)

    # Finally, do one last transfer, which should succeed now
    # that the endpoint is unstalled.
    yield harness.transaction_data_out(addr, epaddr_out, d)

@cocotb.test()
def test_control_transfer_in_nak_data(dut):
    harness = UsbTest(dut)
    yield harness.reset()
    yield harness.connect()

    addr = 22
    yield harness.write(harness.csrs['usb_address'], addr)
    # Get descriptor, Index 0, Type 03, LangId 0000, wLength 64
    setup_data = [0x80, 0x06, 0x00, 0x03, 0x00, 0x00, 0x40, 0x00]
    in_data = [0x04, 0x03, 0x09, 0x04]

    epaddr_in = EndpointType.epaddr(0, EndpointType.IN)
    # yield harness.clear_pending(epaddr_in)

    yield harness.write(harness.csrs['usb_address'], addr)

    # Setup stage
    # -----------
    yield harness.transaction_setup(addr, setup_data)

    # Data stage
    # -----------
    yield harness.set_response(epaddr_in, EndpointResponse.NAK)
    yield harness.host_send_token_packet(PID.IN, addr, epaddr_in)
    yield harness.host_expect_nak()

    yield harness.set_data(epaddr_in, in_data)
    yield harness.set_response(epaddr_in, EndpointResponse.ACK)
    yield harness.host_send_token_packet(PID.IN, addr, epaddr_in)
    yield harness.host_expect_data_packet(PID.DATA1, in_data)
    yield harness.host_send_ack()

# @cocotb.test()
# def test_control_transfer_in_nak_status(dut):
#     harness = UsbTest(dut)
#     yield harness.reset()
#     yield harness.connect()

#     addr = 20
#     setup_data = [0x00, 0x06, 0x00, 0x06, 0x00, 0x00, 0x0A, 0x00]
#     out_data = [0x00, 0x01]

#     epaddr_out = EndpointType.epaddr(0, EndpointType.OUT)
#     epaddr_in = EndpointType.epaddr(0, EndpointType.IN)
#     yield harness.clear_pending(epaddr_out)
#     yield harness.clear_pending(epaddr_in)

#     # Setup stage
#     # -----------
#     yield harness.transaction_setup(addr, setup_data)

#     # Data stage
#     # ----------
#     yield harness.set_response(epaddr_out, EndpointResponse.ACK)
#     yield harness.transaction_data_out(addr, epaddr_out, out_data)

#     # Status stage
#     # ----------
#     yield harness.set_response(epaddr_in, EndpointResponse.NAK)

#     yield harness.host_send_token_packet(PID.IN, addr, epaddr_in)
#     yield harness.host_expect_nak()

#     yield harness.host_send_token_packet(PID.IN, addr, epaddr_in)
#     yield harness.host_expect_nak()

#     yield harness.set_response(epaddr_in, EndpointResponse.ACK)
#     yield harness.host_send_token_packet(PID.IN, addr, epaddr_in)
#     yield harness.host_expect_data_packet(PID.DATA1, [])
#     yield harness.host_send_ack()
#     yield harness.clear_pending(epaddr_in)


@cocotb.test()
def test_control_transfer_in(dut):
    harness = UsbTest(dut)
    yield harness.reset()
    yield harness.connect()

    yield harness.clear_pending(EndpointType.epaddr(0, EndpointType.OUT))
    yield harness.clear_pending(EndpointType.epaddr(0, EndpointType.IN))
    yield harness.write(harness.csrs['usb_address'], 20)

    yield harness.control_transfer_in(
        20,
        # Get descriptor, Index 0, Type 03, LangId 0000, wLength 10?
        [0x80, 0x06, 0x00, 0x06, 0x00, 0x00, 0x0A, 0x00],
        # 12 byte descriptor, max packet size 8 bytes
        [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
            0x08, 0x09, 0x0A, 0x0B],
    )

@cocotb.test()
def test_control_transfer_in_out(dut):
    harness = UsbTest(dut)
    yield harness.reset()
    yield harness.connect()

    yield harness.clear_pending(EndpointType.epaddr(0, EndpointType.OUT))
    yield harness.clear_pending(EndpointType.epaddr(0, EndpointType.IN))
    yield harness.write(harness.csrs['usb_address'], 20)

    yield harness.control_transfer_in(
        20,
        # Get device descriptor
        [0x80, 0x06, 0x00, 0x01, 0x00, 0x00, 0x40, 00],
        # 18 byte descriptor, max packet size 8 bytes
        [0x12, 0x01, 0x10, 0x02, 0x02, 0x00, 0x00, 0x40,
            0x09, 0x12, 0xB1, 0x70, 0x01, 0x01, 0x01, 0x02,
            00, 0x01],
    )

    yield harness.control_transfer_out(
        20,
        # Set address (to 11)
        [0x00, 0x05, 0x0B, 0x00, 0x00, 0x00, 0x00, 0x00],
        # 18 byte descriptor, max packet size 8 bytes
        None,
    )

# @cocotb.test()
# def test_control_transfer_out_nak_data(dut):
#     harness = UsbTest(dut)
#     yield harness.reset()
#     yield harness.connect()

#     addr = 20
#     setup_data = [0x80, 0x06, 0x00, 0x06, 0x00, 0x00, 0x0A, 0x00]
#     out_data = [
#         0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
#         0x08, 0x09, 0x0A, 0x0B,
#     ]

#     epaddr_out = EndpointType.epaddr(0, EndpointType.OUT)
#     yield harness.clear_pending(epaddr_out)

#     # Setup stage
#     # -----------
#     yield harness.transaction_setup(addr, setup_data)

#     # Data stage
#     # ----------
#     yield harness.set_response(epaddr_out, EndpointResponse.NAK)
#     yield harness.host_send_token_packet(PID.OUT, addr, epaddr_out)
#     yield harness.host_send_data_packet(PID.DATA1, out_data)
#     yield harness.host_expect_nak()

#     yield harness.host_send_token_packet(PID.OUT, addr, epaddr_out)
#     yield harness.host_send_data_packet(PID.DATA1, out_data)
#     yield harness.host_expect_nak()

#     #for i in range(200):
#     #    yield

#     yield harness.set_response(epaddr_out, EndpointResponse.ACK)
#     yield harness.host_send_token_packet(PID.OUT, addr, epaddr_out)
#     yield harness.host_send_data_packet(PID.DATA1, out_data)
#     yield harness.host_expect_ack()
#     yield harness.host_expect_data(epaddr_out, out_data)
#     yield harness.clear_pending(epaddr_out)

@cocotb.test()
def test_in_transfer(dut):
    harness = UsbTest(dut)
    yield harness.reset()
    yield harness.connect()

    addr = 28
    epaddr = EndpointType.epaddr(1, EndpointType.IN)
    yield harness.write(harness.csrs['usb_address'], addr)

    d = [0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x8]

    yield harness.clear_pending(epaddr)
    yield harness.set_response(epaddr, EndpointResponse.NAK)

    yield harness.set_data(epaddr, d[:4])
    yield harness.set_response(epaddr, EndpointResponse.ACK)
    yield harness.host_send_token_packet(PID.IN, addr, epaddr)
    yield harness.host_expect_data_packet(PID.DATA1, d[:4])
    yield harness.host_send_ack()

    pending = yield harness.pending(epaddr)
    if pending:
        raise TestFailure("data was still pending")
    yield harness.clear_pending(epaddr)
    yield harness.set_data(epaddr, d[4:])
    yield harness.set_response(epaddr, EndpointResponse.ACK)

    yield harness.host_send_token_packet(PID.IN, addr, epaddr)
    yield harness.host_expect_data_packet(PID.DATA0, d[4:])
    yield harness.host_send_ack()

@cocotb.test()
def test_in_transfer_stuff_last(dut):
    harness = UsbTest(dut)
    yield harness.reset()
    yield harness.connect()

    addr = 28
    epaddr = EndpointType.epaddr(1, EndpointType.IN)
    yield harness.write(harness.csrs['usb_address'], addr)

    d = [0x37, 0x75, 0x00, 0xe0]

    yield harness.clear_pending(epaddr)
    yield harness.set_response(epaddr, EndpointResponse.NAK)

    yield harness.set_data(epaddr, d)
    yield harness.set_response(epaddr, EndpointResponse.ACK)
    yield harness.host_send_token_packet(PID.IN, addr, epaddr)
    yield harness.host_expect_data_packet(PID.DATA1, d)

@cocotb.test()
def test_debug_in(dut):
    harness = UsbTest(dut)
    yield harness.reset()
    yield harness.connect()

    addr = 28
    yield harness.write(harness.csrs['usb_address'], addr)
    # The "scratch" register defaults to 0x12345678 at boot.
    reg_addr = harness.csrs['ctrl_scratch']
    setup_data = [0xc3, 0x00,
                    (reg_addr >> 0) & 0xff,
                    (reg_addr >> 8) & 0xff,
                    (reg_addr >> 16) & 0xff,
                    (reg_addr >> 24) & 0xff, 0x04, 0x00]
    epaddr_in = EndpointType.epaddr(0, EndpointType.IN)
    epaddr_out = EndpointType.epaddr(0, EndpointType.OUT)

    yield harness.transaction_data_in(addr, epaddr_in, [0x2, 0x4, 0x6, 0x8, 0xa], chunk_size=64)

    yield harness.clear_pending(epaddr_out)
    yield harness.clear_pending(epaddr_in)

    # Setup stage
    yield harness.host_send_token_packet(PID.SETUP, addr, epaddr_out)
    yield harness.host_send_data_packet(PID.DATA0, setup_data)
    yield harness.host_expect_ack()

    # Data stage
    yield harness.host_send_token_packet(PID.IN, addr, epaddr_in)
    yield harness.host_expect_data_packet(PID.DATA1, [0x12, 0, 0, 0])
    yield harness.host_send_ack()

    # Status stage
    yield harness.host_send_token_packet(PID.OUT, addr, epaddr_in)
    yield harness.host_send_data_packet(PID.DATA1, [])
    yield harness.host_expect_ack()

# @cocotb.test()
# def test_debug_in_missing_ack(dut):
#     harness = UsbTest(dut)
#     yield harness.reset()
#     yield harness.connect()

#     addr = 28
#     reg_addr = harness.csrs['ctrl_scratch']
#     setup_data = [0xc3, 0x00,
#                     (reg_addr >> 0) & 0xff,
#                     (reg_addr >> 8) & 0xff,
#                     (reg_addr >> 16) & 0xff,
#                     (reg_addr >> 24) & 0xff, 0x04, 0x00]
#     epaddr_in = EndpointType.epaddr(0, EndpointType.IN)
#     epaddr_out = EndpointType.epaddr(0, EndpointType.OUT)

#     # Setup stage
#     yield harness.host_send_token_packet(PID.SETUP, addr, epaddr_out)
#     yield harness.host_send_data_packet(PID.DATA0, setup_data)
#     yield harness.host_expect_ack()

#     # Data stage (missing ACK)
#     yield harness.host_send_token_packet(PID.IN, addr, epaddr_in)
#     yield harness.host_expect_data_packet(PID.DATA1, [0x12, 0, 0, 0])

#     # Data stage
#     yield harness.host_send_token_packet(PID.IN, addr, epaddr_in)
#     yield harness.host_expect_data_packet(PID.DATA1, [0x12, 0, 0, 0])
#     yield harness.host_send_ack()

#     # Status stage
#     yield harness.host_send_token_packet(PID.OUT, addr, epaddr_out)
#     yield harness.host_send_data_packet(PID.DATA1, [])
#     yield harness.host_expect_ack()

@cocotb.test()
def test_debug_out(dut):
    harness = UsbTest(dut)
    yield harness.reset()
    yield harness.connect()

    addr = 28
    yield harness.write(harness.csrs['usb_address'], addr)
    reg_addr = harness.csrs['ctrl_scratch']
    setup_data = [0x43, 0x00,
                    (reg_addr >> 0) & 0xff,
                    (reg_addr >> 8) & 0xff,
                    (reg_addr >> 16) & 0xff,
                    (reg_addr >> 24) & 0xff, 0x04, 0x00]
    ep0in_addr = EndpointType.epaddr(0, EndpointType.IN)
    ep1in_addr = EndpointType.epaddr(1, EndpointType.IN)
    ep0out_addr = EndpointType.epaddr(0, EndpointType.OUT)

    # Force Wishbone to acknowledge the packet
    yield harness.clear_pending(ep0out_addr)
    yield harness.clear_pending(ep0in_addr)
    yield harness.clear_pending(ep1in_addr)

    # Setup stage
    yield harness.host_send_token_packet(PID.SETUP, addr, ep0out_addr)
    yield harness.host_send_data_packet(PID.DATA0, setup_data)
    yield harness.host_expect_ack()

    # Data stage
    yield harness.host_send_token_packet(PID.OUT, addr, ep0out_addr)
    yield harness.host_send_data_packet(PID.DATA1, [0x42, 0, 0, 0])
    yield harness.host_expect_ack()

    # Status stage (wrong endopint)
    yield harness.host_send_token_packet(PID.IN, addr, ep1in_addr)
    yield harness.host_expect_nak()

    # Status stage
    yield harness.host_send_token_packet(PID.IN, addr, ep0in_addr)
    yield harness.host_expect_data_packet(PID.DATA1, [])
    yield harness.host_send_ack()

    new_value = yield harness.read(reg_addr)
    if new_value != 0x42:
        raise TestFailure("memory at 0x{:08x} should be 0x{:08x}, but memory value was 0x{:08x}".format(reg_Addr, 0x42, new_value))
